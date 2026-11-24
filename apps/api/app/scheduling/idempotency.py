"""Idempotent, reconcilable execution of state-changing operations.

Protocol (see docs/idempotency.md):

1. CLAIM  (own transaction, committed): insert an `operations` row for (clinic, idempotency key)
   with ON CONFLICT DO NOTHING. Exactly one concurrent caller wins the insert.
2. WORK   (one transaction): lock the operation row, run the scheduling work, and write the final
   outcome onto the operation row *in the same transaction as the effect*. Commit.
   Because effect and outcome commit atomically, "operation succeeded" and "appointment exists"
   can never disagree.
3. A rolled-back or failed attempt is recorded as `failed` (deterministic business rejection,
   replayed verbatim) or `aborted` (infrastructure failure, nothing committed, safe to re-run).

A retry with the same key and identical request returns the stored outcome. The same key with a
different request fingerprint is rejected. A caller that never saw the response reconciles through
the operation id / idempotency key.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models import Operation
from app.scheduling.errors import (
    DependencyUnavailable,
    IdempotencyConflict,
    OperationInProgress,
    OutcomeUnknown,
    SchedulingError,
)
from app.scheduling.runtime import Clock, Faults

# (response body, appointment id, HTTP status)
WorkResult = tuple[dict[str, Any], uuid.UUID, int]
Work = Callable[[AsyncSession, uuid.UUID], Awaitable[WorkResult]]

INFRASTRUCTURE_ERRORS = (DBAPIError, OSError)


@dataclass(frozen=True)
class Outcome:
    operation_id: uuid.UUID
    http_status: int
    body: dict[str, Any]
    replayed: bool


class _Superseded(Exception):
    """Another attempt took over this operation; this attempt must not commit anything."""


def _stored(row: Operation, replayed: bool) -> Outcome:
    assert row.outcome is not None
    return Outcome(row.id, int(row.outcome["http_status"]), row.outcome["body"], replayed)


async def _claim(
    sm: async_sessionmaker[AsyncSession],
    clinic_id: uuid.UUID,
    patient_id: uuid.UUID,
    operation_type: str,
    key: str,
    fingerprint: str,
    proposal_id: uuid.UUID | None,
    now: datetime,
) -> tuple[str, uuid.UUID, int, Outcome | None]:
    """Returns (mode, operation_id, attempt, stored_outcome); mode in new | replay | wait."""
    lease = get_settings().operation_lease_seconds
    async with sm() as session, session.begin():
        new_id = await session.scalar(
            pg_insert(Operation)
            .values(
                id=uuid.uuid4(),
                clinic_id=clinic_id,
                patient_id=patient_id,
                operation_type=operation_type,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                status="processing",
                proposal_id=proposal_id,
                attempts=1,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_operations_clinic_id_key")
            .returning(Operation.id)
        )
        if new_id is not None:
            return "new", new_id, 1, None

        row = await session.scalar(
            select(Operation).where(
                Operation.clinic_id == clinic_id, Operation.idempotency_key == key
            )
        )
        assert row is not None
        if row.request_fingerprint != fingerprint:
            raise IdempotencyConflict(
                "This idempotency key was already used with a different request.",
                details={"operation_id": str(row.id)},
            )
        if row.status in ("succeeded", "failed"):
            return "replay", row.id, row.attempts, _stored(row, True)

        stale = row.status == "aborted" or (row.updated_at.timestamp() + lease) <= now.timestamp()
        if stale:
            taken = await session.scalar(
                update(Operation)
                .where(
                    Operation.id == row.id,
                    Operation.status == row.status,
                    Operation.updated_at == row.updated_at,
                )
                .values(status="processing", attempts=Operation.attempts + 1, updated_at=now)
                .returning(Operation.attempts)
            )
            if taken is not None:
                return "new", row.id, taken, None
        return "wait", row.id, row.attempts, None


async def execute(
    sm: async_sessionmaker[AsyncSession],
    *,
    clinic_id: uuid.UUID,
    patient_id: uuid.UUID,
    operation_type: str,
    idempotency_key: str,
    fingerprint: str,
    proposal_id: uuid.UUID | None,
    work: Work,
    clock: Clock,
    faults: Faults,
) -> Outcome:
    deadline = time.monotonic() + get_settings().idempotency_wait_seconds
    while True:
        mode, op_id, attempt, stored = await _claim(
            sm,
            clinic_id,
            patient_id,
            operation_type,
            idempotency_key,
            fingerprint,
            proposal_id,
            clock(),
        )
        if mode == "replay":
            assert stored is not None
            return stored
        if mode == "new":
            break
        if time.monotonic() >= deadline:
            raise OperationInProgress(
                "An identical request is still being processed. Retry with the same key.",
                details={"operation_id": str(op_id)},
                headers={"Retry-After": "1"},
            )
        await asyncio.sleep(0.05)

    try:
        await faults.hit("after_claim")
        return await _work_tx(sm, clinic_id, op_id, attempt, work, clock, faults, idempotency_key)
    except OutcomeUnknown:
        raise
    except SchedulingError as err:
        body = {**err.body(), "operation_id": str(op_id)}
        outcome = {"http_status": err.status_code, "body": body}
        if await _finish(sm, op_id, attempt, "failed", outcome, clock()):
            return Outcome(op_id, err.status_code, body, False)
        return await _reconcile(sm, clinic_id, op_id, idempotency_key)
    except _Superseded:
        return await _reconcile(sm, clinic_id, op_id, idempotency_key)
    except INFRASTRUCTURE_ERRORS as exc:
        # The work transaction did not commit, or its commit could not be confirmed. Find out.
        unknown = OutcomeUnknown(
            "The outcome of the operation could not be determined. "
            "Look it up by operation id before retrying.",
            details={"operation_id": str(op_id), "idempotency_key": idempotency_key},
        )
        try:
            settled = await _finish(sm, op_id, attempt, "aborted", None, clock())
            if not settled:  # it had in fact committed (or been superseded): report the truth
                return await _reconcile(sm, clinic_id, op_id, idempotency_key)
        except INFRASTRUCTURE_ERRORS:
            raise unknown from exc
        raise DependencyUnavailable(
            "A scheduling dependency failed. Nothing was changed; retry with the same key.",
            details={"operation_id": str(op_id), "idempotency_key": idempotency_key},
            headers={"Retry-After": "1"},
        ) from exc


async def _work_tx(
    sm: async_sessionmaker[AsyncSession],
    clinic_id: uuid.UUID,
    op_id: uuid.UUID,
    attempt: int,
    work: Work,
    clock: Clock,
    faults: Faults,
    key: str,
) -> Outcome:
    async with sm() as session:
        async with session.begin():
            row = await session.scalar(
                select(Operation).where(Operation.id == op_id).with_for_update()
            )
            if row is None or row.status != "processing" or row.attempts != attempt:
                raise _Superseded
            await faults.hit("in_work")
            body, appointment_id, http_status = await work(session, op_id)
            outcome = {"http_status": http_status, "body": body}
            now = clock()
            row.status = "succeeded"
            row.appointment_id = appointment_id
            row.outcome = outcome
            row.completed_at = now
            row.updated_at = now
            await session.flush()
            await faults.hit("before_commit")
    # Committed. A failure from here on only loses the response, never the effect.
    try:
        await faults.hit("after_commit")
    except Exception as exc:
        raise OutcomeUnknown(
            "The operation committed but the response was lost. "
            "Look it up by operation id or retry with the same idempotency key.",
            details={"operation_id": str(op_id), "idempotency_key": key},
        ) from exc
    return Outcome(op_id, http_status, body, False)


async def _finish(
    sm: async_sessionmaker[AsyncSession],
    op_id: uuid.UUID,
    attempt: int,
    status: str,
    outcome: dict[str, Any] | None,
    now: datetime,
) -> bool:
    """Record a non-success ending. Returns False if the operation had already settled."""
    async with sm() as session, session.begin():
        values: dict[str, Any] = {"status": status, "updated_at": now}
        if status == "failed":
            values.update(outcome=outcome, completed_at=now)
        done = await session.scalar(
            update(Operation)
            .where(
                Operation.id == op_id,
                Operation.status == "processing",
                Operation.attempts == attempt,
            )
            .values(**values)
            .returning(Operation.id)
        )
        return done is not None


async def _reconcile(
    sm: async_sessionmaker[AsyncSession], clinic_id: uuid.UUID, op_id: uuid.UUID, key: str
) -> Outcome:
    async with sm() as session:
        row = await session.scalar(select(Operation).where(Operation.id == op_id))
    if row is not None and row.status in ("succeeded", "failed"):
        return _stored(row, True)
    raise OperationInProgress(
        "The operation is being processed by another request. Retry with the same key.",
        details={"operation_id": str(op_id), "idempotency_key": key},
        headers={"Retry-After": "1"},
    )
