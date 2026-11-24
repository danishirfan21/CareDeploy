"""Simulated configuration deployment (M5): assessment, promotion and rollback.

A deployment selects which immutable published version new voice sessions use. It does not
provision anything. Readiness is the M4 engine's answer, recalculated on the server for every
action; the client cannot supply or override it.

Concurrency strategy (see docs/deployments.md): every change takes a row lock on the clinic
(`SELECT ... FOR UPDATE`), so two promotions for one clinic run one after the other. Inside the
lock the caller's `expected_active_version` is compared with the real active version
(compare-and-swap) and readiness is recalculated. The partial unique index on active
deployments is the backstop that makes an ambiguous pointer impossible even if code is wrong.

Idempotency: `idempotency_key` is scoped to the clinic. The same key with the same request returns
the original result; the same key with a different request is `409 idempotency_conflict`. Without
a key, asking for the version that is already active is `409 already_active` and writes nothing.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.evals import analysis
from app.evals.loader import load_suite, suite_hash
from app.evals.service import sweep_stale
from app.evals.store import jsonable, latest_views
from app.models import Clinic, ConfigVersion, Deployment, DeploymentEvent
from app.models.deployments import ENVIRONMENT, ENVIRONMENT_LABEL
from app.schemas.ops import (
    DeploymentAssessment,
    DeploymentCheck,
    DeploymentEventDetail,
    DeploymentEventRead,
    DeploymentRead,
    DeploymentState,
)

DEV_ACTOR = "local-dev-operator"  # single-operator development limitation, see docs/deployments.md
LIVE_PENDING = (
    "Workflow checks passed. Real voice verification has not been completed: speech, "
    "turn-taking and a language model's tool choices are unverified."
)
NO_ACTIVE_MESSAGE = (
    "This clinic has no active deployment. Evaluate a published version and promote it to "
    f"{ENVIRONMENT_LABEL} before starting a call."
)


class DeployError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


# ----------------------------------------------------------------------------- reads ---------
async def active_deployment(db: AsyncSession, clinic_id: uuid.UUID) -> Deployment | None:
    return await db.scalar(
        select(Deployment).where(
            Deployment.clinic_id == clinic_id,
            Deployment.environment == ENVIRONMENT,
            Deployment.status == "active",
        )
    )


def to_read(d: Deployment) -> DeploymentRead:
    return DeploymentRead(
        id=d.id,
        clinic_id=d.clinic_id,
        config_version=d.config_version,
        environment=d.environment,
        environment_label=ENVIRONMENT_LABEL,
        status=d.status,  # type: ignore[arg-type]
        action=d.action,  # type: ignore[arg-type]
        activated_at=d.activated_at,
        deactivated_at=d.deactivated_at,
        actor=d.actor,
        readiness_level=d.readiness_level,
        restored_from_id=d.restored_from_id,
    )


def _summary(e: DeploymentEvent) -> str:
    if e.kind == "seeded":
        return f"Version {e.to_version} activated by the sample seed (not evaluated)."
    if e.kind == "rolled_back":
        return f"Version {e.to_version} restored through rollback from version {e.from_version}."
    if e.from_version is None:
        return f"Version {e.to_version} promoted."
    return f"Version {e.to_version} promoted, replacing version {e.from_version}."


def event_read(e: DeploymentEvent) -> DeploymentEventRead:
    return DeploymentEventRead(
        id=e.id,
        deployment_id=e.deployment_id,
        kind=e.kind,  # type: ignore[arg-type]
        from_version=e.from_version,
        to_version=e.to_version,
        actor=e.actor,
        occurred_at=e.occurred_at,
        summary=_summary(e),
    )


async def state(db: AsyncSession, clinic: Clinic) -> DeploymentState:
    active = await active_deployment(db, clinic.id)
    latest = await db.scalar(
        select(ConfigVersion.version)
        .where(ConfigVersion.clinic_id == clinic.id)
        .order_by(ConfigVersion.version.desc())
        .limit(1)
    )
    return DeploymentState(
        clinic_id=clinic.id,
        environment=ENVIRONMENT,
        environment_label=ENVIRONMENT_LABEL,
        active=to_read(active) if active else None,
        latest_published_version=latest,
        note=(
            f"{ENVIRONMENT_LABEL} selects the version used by new development voice sessions in "
            "CareDeploy. It is not a real healthcare production deployment."
        ),
    )


async def history(db: AsyncSession, clinic_id: uuid.UUID, limit: int) -> list[DeploymentEventRead]:
    rows = (
        await db.scalars(
            select(DeploymentEvent)
            .where(DeploymentEvent.clinic_id == clinic_id)
            .order_by(DeploymentEvent.occurred_at.desc(), DeploymentEvent.id)
            .limit(limit)
        )
    ).all()
    return [event_read(e) for e in rows]


async def event_detail(
    db: AsyncSession, clinic_id: uuid.UUID, event_id: uuid.UUID
) -> DeploymentEventDetail | None:
    e = await db.get(DeploymentEvent, event_id)
    if e is None or e.clinic_id != clinic_id:
        return None
    d = await db.get(Deployment, e.deployment_id)
    assert d is not None
    return DeploymentEventDetail(
        **event_read(e).model_dump(), readiness=e.readiness, deployment=to_read(d)
    )


# --------------------------------------------------------------------------- assessment ------
async def _was_deployed(db: AsyncSession, clinic_id: uuid.UUID, version: int) -> bool:
    return (
        await db.scalar(
            select(Deployment.id)
            .where(Deployment.clinic_id == clinic_id, Deployment.config_version == version)
            .limit(1)
        )
    ) is not None


async def assess(
    db: AsyncSession,
    clinic: Clinic,
    version: int,
    action: str,
    settings: Settings,
    now: datetime,
) -> DeploymentAssessment:
    """Decide whether `version` may become active. Raises DeployError 404 for an unknown version
    (a version number from another clinic is exactly that: unknown here)."""
    if action not in ("promote", "rollback"):
        raise ValueError(action)
    exists = await db.scalar(
        select(ConfigVersion.id).where(
            ConfigVersion.clinic_id == clinic.id, ConfigVersion.version == version
        )
    )
    if exists is None:
        raise DeployError(
            404, "version_not_found", f"Version {version} is not published for this clinic."
        )
    await sweep_stale(db, clinic.id)
    views = await latest_views(db, clinic.id, version)
    readiness = analysis.compute_readiness(version, views)
    wf = readiness["modes"]["workflow"]
    run = views.get("workflow")
    active = await active_deployment(db, clinic.id)
    checks: list[DeploymentCheck] = [
        DeploymentCheck(
            id="published",
            passed=True,
            message=f"Version {version} is a published, immutable snapshot of this clinic.",
        )
    ]

    full_pass = wf["state"] == "passed"
    if wf["state"] == "passed":
        msg = "A completed full-suite workflow run passed every required scenario."
    elif wf["state"] == "not_run":
        msg = "No workflow evaluation has been run for this version."
    elif wf["state"] == "partial":
        msg = "Only part of the suite was run. Mandatory scenarios must all run."
    elif wf["state"] == "incomplete":
        msg = "The latest workflow run did not finish (runner error, timeout or cancellation)."
    else:
        msg = "The latest full workflow run did not pass every required scenario."
    checks.append(DeploymentCheck(id="required_coverage", passed=full_pass, message=msg))

    crit = readiness["blocking"]
    checks.append(
        DeploymentCheck(
            id="critical_scenarios",
            passed=not crit,
            message="No critical scenario failed."
            if not crit
            else f"{len(crit)} critical scenario(s) did not pass: "
            + ", ".join(b["scenario_id"] for b in crit),
        )
    )

    current_suite = suite_hash(load_suite())
    suite_ok = run is not None and run.suite_hash == current_suite
    if run is None:
        suite_msg = "No evaluation evidence exists to compare with the current scenarios."
    elif suite_ok:
        suite_msg = "The evidence was produced by the current scenario suite."
    else:
        suite_msg = (
            "The evidence was produced by an older scenario suite. Run the evaluation again."
        )
    checks.append(DeploymentCheck(id="evidence_current", passed=suite_ok, message=suite_msg))

    fresh = False
    fresh_msg = "No finished evaluation run exists."
    if run is not None and run.finished_at:
        finished = datetime.fromisoformat(run.finished_at)
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=UTC)
        age = now - finished
        limit = timedelta(days=settings.deployment_evidence_max_age_days)
        fresh = age <= limit
        fresh_msg = (
            f"The evidence is {max(age.days, 0)} day(s) old (limit "
            f"{settings.deployment_evidence_max_age_days})."
            if fresh
            else f"The evidence is {age.days} day(s) old; the limit is "
            f"{settings.deployment_evidence_max_age_days}. Run the evaluation again."
        )
    checks.append(DeploymentCheck(id="evidence_recent", passed=fresh, message=fresh_msg))

    if action == "rollback":
        prior = await _was_deployed(db, clinic.id, version)
        checks.append(
            DeploymentCheck(
                id="rollback_target",
                passed=prior,
                message="This version was deployed before."
                if prior
                else "Rollback can only restore a version that was deployed before.",
            )
        )
    differs = active is None or active.config_version != version
    checks.append(
        DeploymentCheck(
            id="not_active",
            passed=differs,
            message="This version is not the active one."
            if differs
            else "This version is already active.",
        )
    )

    failed = [c for c in checks if not c.passed]
    eligible = not failed
    if eligible:
        headline = f"Eligible for {ENVIRONMENT_LABEL}."
    else:
        headline = f"Deployment blocked. {len(failed)} requirement{'s' if len(failed) != 1 else ''} not met."
    live = readiness["live_verification"]
    return DeploymentAssessment(
        clinic_id=clinic.id,
        config_version=version,
        action=action,  # type: ignore[arg-type]
        eligible=eligible,
        decision="allowed" if eligible else "blocked",
        headline=headline,
        live_verification=live,
        live_verification_message=LIVE_PENDING if live != "complete" else "Verified.",
        checks=checks,
        readiness=jsonable(readiness),
        active_version=active.config_version if active else None,
        evaluated_run_id=wf.get("run_id"),
    )


# ----------------------------------------------------------------------------- changes -------
def _request_hash(action: str, version: int, expected: int | None) -> str:
    raw = json.dumps([action, version, expected], separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


async def _apply(
    db: AsyncSession,
    clinic_id: uuid.UUID,
    *,
    action: str,
    version: int,
    expected: int | None,
    key: str | None,
    settings: Settings,
    now: datetime,
) -> tuple[Deployment, DeploymentEvent, bool]:
    # Serialize every change for this clinic. Held until commit or rollback.
    clinic = await db.scalar(select(Clinic).where(Clinic.id == clinic_id).with_for_update())
    if clinic is None:
        raise DeployError(404, "clinic_not_found", "Clinic not found.")

    req_hash = _request_hash(action, version, expected)
    if key:
        prior = await db.scalar(
            select(Deployment).where(
                Deployment.clinic_id == clinic_id, Deployment.idempotency_key == key
            )
        )
        if prior is not None:
            if prior.request_hash != req_hash:
                raise DeployError(
                    409,
                    "idempotency_conflict",
                    "This idempotency key was already used for a different request.",
                )
            ev = await db.scalar(
                select(DeploymentEvent).where(DeploymentEvent.deployment_id == prior.id)
            )
            assert ev is not None
            return prior, ev, True

    active = await active_deployment(db, clinic_id)
    current = active.config_version if active else None
    if expected != current:
        raise DeployError(
            409,
            "concurrent_modification",
            "The active version changed since this page loaded. Reload and review before "
            "deploying again.",
            active_version=current,
        )
    assessment = await assess(db, clinic, version, action, settings, now)
    if not assessment.eligible:
        failed = [c for c in assessment.checks if not c.passed]
        if any(c.id == "not_active" for c in failed) and len(failed) == 1:
            raise DeployError(
                409, "already_active", f"Version {version} is already the active deployment."
            )
        raise DeployError(
            409,
            "rollback_blocked" if action == "rollback" else "deployment_blocked",
            assessment.headline,
            checks=[c.model_dump() for c in failed],
        )

    restored: uuid.UUID | None = None
    if action == "rollback":
        restored = await db.scalar(
            select(Deployment.id)
            .where(Deployment.clinic_id == clinic_id, Deployment.config_version == version)
            .order_by(Deployment.activated_at.desc())
            .limit(1)
        )
    if active is not None:
        active.status = "superseded"
        active.deactivated_at = now
        await db.flush()
    evidence = {"assessment": assessment.model_dump(mode="json"), "recorded_at": now.isoformat()}
    dep = Deployment(
        id=uuid.uuid4(),
        clinic_id=clinic_id,
        config_version=version,
        environment=ENVIRONMENT,
        status="active",
        action=action,
        activated_at=now,
        actor=DEV_ACTOR,
        readiness=evidence,
        readiness_level=str(assessment.readiness["level"]),
        restored_from_id=restored,
        idempotency_key=key,
        request_hash=req_hash if key else None,
    )
    db.add(dep)
    await db.flush()
    ev = DeploymentEvent(
        id=uuid.uuid4(),
        clinic_id=clinic_id,
        deployment_id=dep.id,
        kind="rolled_back" if action == "rollback" else "promoted",
        from_version=current,
        to_version=version,
        actor=DEV_ACTOR,
        readiness=evidence,
        occurred_at=now,
    )
    db.add(ev)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise DeployError(
            409,
            "concurrent_modification",
            "Another deployment change for this clinic completed first. Reload and try again.",
        ) from None
    return dep, ev, False


async def promote(
    db: AsyncSession,
    clinic_id: uuid.UUID,
    version: int,
    expected: int | None,
    key: str | None,
    settings: Settings,
    now: datetime,
) -> tuple[Deployment, DeploymentEvent, bool]:
    return await _apply(
        db, clinic_id, action="promote", version=version, expected=expected, key=key,
        settings=settings, now=now,
    )  # fmt: skip


async def rollback(
    db: AsyncSession,
    clinic_id: uuid.UUID,
    version: int,
    expected: int | None,
    key: str | None,
    settings: Settings,
    now: datetime,
) -> tuple[Deployment, DeploymentEvent, bool]:
    return await _apply(
        db, clinic_id, action="rollback", version=version, expected=expected, key=key,
        settings=settings, now=now,
    )  # fmt: skip


async def seed_activation(
    db: AsyncSession, clinic_id: uuid.UUID, version: int, now: datetime | None = None
) -> Deployment:
    """Activate a version for the sample seed and for test setup only. It records honestly that
    the version was not evaluated. The API never exposes this path."""
    when = now or datetime.now(UTC)
    clinic = await db.scalar(select(Clinic).where(Clinic.id == clinic_id).with_for_update())
    assert clinic is not None
    active = await active_deployment(db, clinic_id)
    if active is not None:
        if active.config_version == version:
            return active
        active.status = "superseded"
        active.deactivated_at = when
        await db.flush()
    evidence = {
        "assessment": None,
        "note": "Activated by the sample seed without evaluation.",
        "recorded_at": when.isoformat(),
    }
    dep = Deployment(
        id=uuid.uuid4(),
        clinic_id=clinic_id,
        config_version=version,
        environment=ENVIRONMENT,
        status="active",
        action="seed",
        activated_at=when,
        actor="seed",
        readiness=evidence,
        readiness_level="not_evaluated",
    )
    db.add(dep)
    await db.flush()
    db.add(
        DeploymentEvent(
            id=uuid.uuid4(),
            clinic_id=clinic_id,
            deployment_id=dep.id,
            kind="seeded",
            from_version=active.config_version if active else None,
            to_version=version,
            actor="seed",
            readiness=evidence,
            occurred_at=when,
        )
    )
    await db.flush()
    return dep
