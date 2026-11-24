"""Voice session API (M3).

Two audiences, two authentication models:

* Browser (single-operator development tool, no user accounts): create a session, read it, read
  its events, end it. The session is bound to one clinic and one published configuration version.
* Worker (the LiveKit agent process): claim a session, report events/state, complete it. Every
  worker route requires `X-Voice-Worker-Secret`. The worker learns its context here, never from
  room metadata.

Errors are `{"detail": ...}` like M1; voice-specific ones carry `{"code", "message"}`.
"""

import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.deploy.service import NO_ACTIVE_MESSAGE, active_deployment
from app.models import CallEvent, CallSession, Clinic, ConfigVersion, Deployment
from app.ops.calls import classify_session
from app.ops.redact import scrub
from app.scheduling.runtime import Clock, get_clock
from app.schemas.clinic import ClinicConfig
from app.schemas.voice import (
    CallComplete,
    CallEventRead,
    CallEventsAccepted,
    CallEventsIn,
    CallEventsOut,
    EndRequest,
    LiveStateIn,
    VoiceSessionCreated,
    VoiceSessionRead,
    WorkerClaim,
    WorkerContext,
)

router = APIRouter(tags=["voice"])

DEV_ACTOR = "local-dev-operator"  # single-operator development limitation: see docs/voice-agent.md
TERMINAL = {"completed", "failed", "abandoned"}

Db = Annotated[AsyncSession, Depends(get_session)]


def _err(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message, **extra})


def require_voice_configured(settings: Settings) -> None:
    missing = settings.voice_missing
    if missing:
        raise _err(
            503,
            "voice_not_configured",
            "Live voice is not configured on this server. Set the missing environment "
            "variables and restart the API.",
            missing=missing,
        )


async def require_worker(
    x_voice_worker_secret: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.voice_worker_secret:
        raise _err(503, "voice_not_configured", "Worker channel is disabled (no secret set).")
    if not x_voice_worker_secret or not hmac.compare_digest(
        x_voice_worker_secret.encode(), settings.voice_worker_secret.encode()
    ):
        raise _err(401, "worker_unauthorized", "Invalid worker credentials.")


async def _published(
    db: AsyncSession, clinic_id: uuid.UUID, version: int | None = None
) -> tuple[Clinic, ConfigVersion]:
    clinic = await db.get(Clinic, clinic_id)
    if clinic is None:
        raise HTTPException(404, detail="Clinic not found.")
    query = select(ConfigVersion).where(ConfigVersion.clinic_id == clinic_id)
    query = (
        query.where(ConfigVersion.version == version)
        if version is not None
        else query.order_by(ConfigVersion.version.desc()).limit(1)
    )
    cv = await db.scalar(query)
    if cv is None:
        raise _err(
            409,
            "clinic_not_configured",
            "This clinic has no published configuration. Publish it before starting a call.",
        )
    return clinic, cv


async def _active(
    db: AsyncSession, clinic_id: uuid.UUID
) -> tuple[Clinic, ConfigVersion, Deployment]:
    """New sessions use the active deployment, never "the latest published version"."""
    clinic = await db.get(Clinic, clinic_id)
    if clinic is None:
        raise HTTPException(404, detail="Clinic not found.")
    dep = await active_deployment(db, clinic_id)
    if dep is None:
        if (
            await db.scalar(
                select(ConfigVersion.id).where(ConfigVersion.clinic_id == clinic_id).limit(1)
            )
            is None
        ):
            raise _err(
                409,
                "clinic_not_configured",
                "This clinic has no published configuration. Publish it before starting a call.",
            )
        raise _err(409, "no_active_deployment", NO_ACTIVE_MESSAGE)
    cv = await db.scalar(
        select(ConfigVersion).where(
            ConfigVersion.clinic_id == clinic_id, ConfigVersion.version == dep.config_version
        )
    )
    if cv is None:  # unreachable: composite foreign key; fail closed anyway
        raise _err(409, "no_active_deployment", NO_ACTIVE_MESSAGE)
    return clinic, cv, dep


async def _session(db: AsyncSession, session_id: uuid.UUID) -> CallSession:
    cs = await db.get(CallSession, session_id)
    if cs is None:
        raise HTTPException(404, detail="Call session not found.")
    return cs


def mint_token(settings: Settings, cs: CallSession, expires: timedelta) -> str:
    """Participant token for exactly one room: join + publish microphone + subscribe. No data
    publishing, no room admin, no API secret. It dispatches the named agent into that room."""
    from livekit import api

    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(f"operator-{cs.id.hex[:12]}")
        .with_name("Local operator")
        .with_ttl(expires)
        .with_metadata(json.dumps({"call_session_id": str(cs.id), "clinic_id": str(cs.clinic_id)}))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=cs.room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=False,
                can_publish_sources=["microphone"],
            )
        )
        .with_room_config(
            api.RoomConfiguration(
                agents=[
                    api.RoomAgentDispatch(agent_name=settings.voice_agent_name, metadata=str(cs.id))
                ]
            )
        )
    )
    return token.to_jwt()


def _read(cs: CallSession, clinic_name: str, agent_name: str) -> VoiceSessionRead:
    return VoiceSessionRead(
        call_session_id=cs.id,
        clinic_id=cs.clinic_id,
        clinic_name=clinic_name,
        agent_name=agent_name,
        config_version=cs.config_version,
        status=cs.status,  # type: ignore[arg-type]
        outcome=cs.outcome,  # type: ignore[arg-type]
        summary=cs.summary,
        created_at=cs.created_at,
        started_at=cs.started_at,
        ended_at=cs.ended_at,
        duration_seconds=cs.duration_seconds,
        ended_by=cs.ended_by,
        escalation_reason=cs.escalation_reason,
        error=cs.error,
        operation_ids=list(cs.operation_ids or []),
        metrics=cs.metrics or {},
        provider_usage=cs.provider_usage or {},
        live_state=cs.live_state or {},
        dev_actor=cs.dev_actor,
    )


async def _read_full(db: AsyncSession, cs: CallSession) -> VoiceSessionRead:
    clinic, cv = await _published(db, cs.clinic_id, cs.config_version)
    config = ClinicConfig.model_validate(cv.snapshot)
    return _read(cs, clinic.name, config.agent.agent_name)


# ------------------------------------------------------------------ browser-facing -----------
@router.post("/clinics/{clinic_id}/voice/sessions", status_code=201)
async def create_session(
    clinic_id: uuid.UUID,
    db: Db,
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> VoiceSessionCreated:
    require_voice_configured(settings)
    clinic, cv, dep = await _active(db, clinic_id)
    config = ClinicConfig.model_validate(cv.snapshot)
    now = clock()
    expires = timedelta(seconds=settings.voice_token_ttl_seconds)
    session_id = uuid.uuid4()
    cs = CallSession(
        id=session_id,
        clinic_id=clinic.id,
        config_version=cv.version,
        deployment_id=dep.id,
        room_name=f"call-{session_id}",
        status="created",
        dev_actor=DEV_ACTOR,
        created_at=now,
        token_expires_at=now + expires,
        operation_ids=[],
        metrics={},
        provider_usage={},
        live_state={},
    )
    db.add(cs)
    await db.commit()
    return VoiceSessionCreated(
        call_session_id=cs.id,
        clinic_id=clinic.id,
        clinic_name=clinic.name,
        agent_name=config.agent.agent_name,
        config_version=cv.version,
        room_name=cs.room_name,
        livekit_url=settings.livekit_url,
        token=mint_token(settings, cs, expires),
        token_expires_at=cs.token_expires_at,
        created_at=cs.created_at,
        dev_actor=DEV_ACTOR,
    )


@router.get("/voice/sessions/{session_id}")
async def get_session_read(session_id: uuid.UUID, db: Db) -> VoiceSessionRead:
    return await _read_full(db, await _session(db, session_id))


@router.get("/voice/sessions/{session_id}/events")
async def list_events(
    session_id: uuid.UUID, db: Db, after_seq: Annotated[int, Query(ge=-1)] = -1
) -> CallEventsOut:
    await _session(db, session_id)
    rows = (
        await db.scalars(
            select(CallEvent)
            .where(CallEvent.call_session_id == session_id, CallEvent.seq > after_seq)
            .order_by(CallEvent.seq, CallEvent.received_at)
            .limit(500)
        )
    ).all()
    return CallEventsOut(
        events=[
            CallEventRead(
                event_id=r.event_id,
                seq=r.seq,
                kind=r.kind,  # type: ignore[arg-type]
                occurred_at=r.occurred_at,
                payload=r.payload,
                received_at=r.received_at,
            )
            for r in rows
        ]
    )


def _finish(
    cs: CallSession, status: str, now: datetime, ended_by: str, outcome: str | None = None
) -> None:
    if cs.status in TERMINAL:
        return
    cs.status = status
    cs.ended_at = now
    cs.ended_by = ended_by
    cs.duration_seconds = round((now - (cs.started_at or cs.created_at)).total_seconds(), 3)
    if outcome and not cs.outcome:
        cs.outcome = outcome


@router.post("/voice/sessions/{session_id}/end")
async def end_session(
    session_id: uuid.UUID, body: EndRequest, db: Db, clock: Clock = Depends(get_clock)
) -> VoiceSessionRead:
    """The browser left the room. A call nobody answered is `abandoned`; otherwise `completed`
    (the worker may still add its outcome afterwards)."""
    cs = await _session(db, session_id)
    if cs.status == "created":
        _finish(
            cs, "failed" if body.reason == "connection_failed" else "abandoned", clock(), "browser"
        )
        if body.reason in ("connection_failed", "microphone_denied"):
            cs.error = body.reason
    elif cs.status == "active":
        _finish(cs, "completed", clock(), "browser")
    if cs.status in TERMINAL:
        await classify_session(db, cs, clock())
    await db.commit()
    return await _read_full(db, cs)


# ------------------------------------------------------------------ worker-facing ------------
@router.post("/voice/worker/sessions/{session_id}/claim", dependencies=[Depends(require_worker)])
async def claim(
    session_id: uuid.UUID, body: WorkerClaim, db: Db, clock: Clock = Depends(get_clock)
) -> WorkerContext:
    cs = await _session(db, session_id)
    if body.room_name != cs.room_name:
        raise _err(403, "room_mismatch", "Room does not belong to this call session.")
    now = clock()
    if cs.status != "created":
        raise _err(409, "session_not_claimable", f"Call session is already {cs.status}.")
    if now > cs.token_expires_at + timedelta(minutes=5):
        cs.status = "abandoned"
        await db.commit()
        raise _err(409, "session_expired", "Call session expired before the worker joined.")
    cs.status = "active"
    cs.started_at = now
    await db.commit()
    _, cv = await _published(db, cs.clinic_id, cs.config_version)
    return WorkerContext(
        call_session_id=cs.id,
        clinic_id=cs.clinic_id,
        config_version=cs.config_version,
        room_name=cs.room_name,
        created_at=cs.created_at,
        config=ClinicConfig.model_validate(cv.snapshot),
    )


@router.post("/voice/worker/sessions/{session_id}/events", dependencies=[Depends(require_worker)])
async def ingest_events(session_id: uuid.UUID, body: CallEventsIn, db: Db) -> CallEventsAccepted:
    cs = await _session(db, session_id)
    rows = [
        {
            "id": uuid.uuid4(),
            "call_session_id": cs.id,
            "clinic_id": cs.clinic_id,
            "event_id": e.event_id,
            "seq": e.seq,
            "kind": e.kind,
            "occurred_at": e.occurred_at
            if e.occurred_at.tzinfo
            else e.occurred_at.replace(tzinfo=UTC),
            "payload": scrub(e.payload),
        }
        for e in body.events
    ]
    stmt = (
        pg_insert(CallEvent)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_call_events_session_event")
        .returning(CallEvent.id)
    )
    inserted = len((await db.execute(stmt)).all())
    await db.commit()
    return CallEventsAccepted(accepted=inserted, duplicates=len(rows) - inserted)


@router.put("/voice/worker/sessions/{session_id}/state", dependencies=[Depends(require_worker)])
async def put_state(
    session_id: uuid.UUID, body: LiveStateIn, db: Db, clock: Clock = Depends(get_clock)
) -> dict[str, bool]:
    cs = await _session(db, session_id)
    cs.live_state = scrub(body.state)
    cs.live_state_at = clock()
    await db.commit()
    return {"ok": True}


@router.post("/voice/worker/sessions/{session_id}/complete", dependencies=[Depends(require_worker)])
async def complete(
    session_id: uuid.UUID, body: CallComplete, db: Db, clock: Clock = Depends(get_clock)
) -> VoiceSessionRead:
    cs = await _session(db, session_id)
    _finish(cs, body.status, clock(), "worker")
    # The worker's findings are authoritative even if the browser hung up first.
    if body.outcome:
        cs.outcome = body.outcome
    if body.summary:
        cs.summary = body.summary
    if body.escalation_reason:
        cs.escalation_reason = body.escalation_reason
    if body.error:
        cs.error = body.error
    if cs.status == "abandoned" and body.status == "completed" and cs.started_at:
        cs.status = "completed"
    if body.operation_ids:
        cs.operation_ids = list(dict.fromkeys([*(cs.operation_ids or []), *body.operation_ids]))
    cs.metrics = scrub(body.metrics)
    cs.provider_usage = scrub(body.provider_usage)
    cs.live_state = {**(cs.live_state or {}), "ended": True}
    await classify_session(db, cs, clock())
    await db.commit()
    return await _read_full(db, cs)
