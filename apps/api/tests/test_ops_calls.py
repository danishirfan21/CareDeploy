"""Call operations (M5): history, detail, classification wiring and aggregate metrics."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.models import CallEvent, CallSession, Operation
from app.ops.pricing import UNAVAILABLE_NO_USAGE
from tests.world import World

# 2026-03-04 03:30 UTC is still 2026-03-03 21:30 in America/Chicago (UTC-6 in early March).
BOUNDARY = datetime(2026, 3, 4, 3, 30, tzinfo=UTC)


async def add_call(
    world: World,
    clinic_name: str = "Northstar Family Medicine",
    *,
    status: str = "completed",
    outcome: str | None = None,
    created: datetime = BOUNDARY,
    duration: float | None = 60.0,
    ops: list[tuple[str, str]] | None = None,
    usage: dict[str, Any] | None = None,
    **fields: Any,
) -> uuid.UUID:
    clinic = world.clinics[clinic_name]
    patient = next(p for p in world.patients.values() if p.clinic.id == clinic.id)
    sid = uuid.uuid4()
    op_ids: list[str] = []
    async with get_sessionmaker()() as s:
        for kind, st in ops or []:
            op = Operation(
                clinic_id=clinic.id,
                patient_id=patient.id,
                operation_type=kind,
                idempotency_key=str(uuid.uuid4()),
                request_fingerprint="f" * 64,
                status=st,
            )
            s.add(op)
            await s.flush()
            op_ids.append(str(op.id))
        s.add(
            CallSession(
                id=sid,
                clinic_id=clinic.id,
                config_version=1,
                room_name=f"call-{sid}",
                status=status,
                outcome=outcome,
                dev_actor="test",
                created_at=created,
                started_at=created if status != "created" else None,
                ended_at=created + timedelta(seconds=duration or 0)
                if status in ("completed", "failed", "abandoned")
                else None,
                duration_seconds=duration,
                token_expires_at=created + timedelta(minutes=10),
                operation_ids=op_ids,
                metrics={},
                provider_usage=usage or {},
                live_state={},
                **fields,
            )
        )
        await s.commit()
    return sid


async def add_event(
    sid: uuid.UUID, clinic_id: uuid.UUID, seq: int, kind: str, payload: dict[str, Any]
) -> None:
    async with get_sessionmaker()() as s:
        s.add(
            CallEvent(
                call_session_id=sid,
                clinic_id=clinic_id,
                event_id=f"e{seq}-{uuid.uuid4().hex[:6]}",
                seq=seq,
                kind=kind,
                occurred_at=BOUNDARY + timedelta(seconds=seq),
                payload=payload,
            )
        )
        await s.commit()


def calls_url(world: World, name: str = "Northstar Family Medicine") -> str:
    return f"/api/clinics/{world.clinics[name].id}/calls"


async def test_list_is_scoped_filtered_and_paginated(world: World) -> None:
    a = await add_call(world, outcome="information_provided")
    await add_call(world, "Lakeside Dermatology", outcome="information_provided")
    await add_call(world, status="abandoned", created=BOUNDARY + timedelta(minutes=1))
    await add_call(world, status="active", created=BOUNDARY + timedelta(minutes=2))

    r = await world.client.get(calls_url(world))
    body = r.json()
    assert r.status_code == 200 and body["total"] == 3
    assert {i["clinic_name"] for i in body["items"]} == {"Northstar Family Medicine"}
    # Newest first; the in-progress call has no class yet.
    assert body["items"][0]["outcome_class"] is None
    assert body["items"][0]["outcome_label"] == "In progress"

    only = (await world.client.get(calls_url(world), params={"outcome": "abandoned"})).json()
    assert only["total"] == 1 and only["items"][0]["outcome_class"] == "abandoned"
    prog = (await world.client.get(calls_url(world), params={"outcome": "in_progress"})).json()
    assert prog["total"] == 1

    page = (await world.client.get(calls_url(world), params={"limit": 2, "offset": 2})).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert page["items"][0]["id"] == str(a)

    bad = await world.client.get(calls_url(world), params={"limit": 1000})
    assert bad.status_code == 422
    bad = await world.client.get(calls_url(world), params={"outcome": "great"})
    assert bad.status_code == 422
    bad = await world.client.get(
        calls_url(world), params={"date_from": "2026-03-05", "date_to": "2026-03-01"}
    )
    assert bad.status_code == 422
    assert (await world.client.get(f"/api/clinics/{uuid.uuid4()}/calls")).status_code == 404


async def test_date_filter_uses_the_clinic_time_zone(world: World) -> None:
    await add_call(world, outcome="information_provided")  # 21:30 on 2026-03-03 Chicago time
    local_day = (
        await world.client.get(
            calls_url(world), params={"date_from": "2026-03-03", "date_to": "2026-03-03"}
        )
    ).json()
    utc_day = (
        await world.client.get(
            calls_url(world), params={"date_from": "2026-03-04", "date_to": "2026-03-04"}
        )
    ).json()
    assert local_day["total"] == 1
    assert utc_day["total"] == 0


async def test_search_matches_safe_metadata_only(world: World) -> None:
    sid = await add_call(world, outcome="information_provided", summary="Asked about flu shots")
    assert (await world.client.get(calls_url(world), params={"q": "flu"})).json()["total"] == 1
    assert (await world.client.get(calls_url(world), params={"q": str(sid)[:8]})).json()[
        "total"
    ] == 1
    # Wildcards are literal text, not patterns.
    assert (await world.client.get(calls_url(world), params={"q": "%"})).json()["total"] == 0
    assert (await world.client.get(calls_url(world), params={"q": "nonsense"})).json()["total"] == 0


async def test_classification_follows_the_ledger_not_the_claim(world: World) -> None:
    ok = await add_call(world, outcome="appointment_booked", ops=[("book", "succeeded")])
    unproven = await add_call(world, outcome="appointment_booked")
    pending = await add_call(world, outcome="appointment_booked", ops=[("book", "processing")])
    esc = await add_call(world, outcome="escalated", escalation_reason="asked for a person")
    items = {i["id"]: i for i in (await world.client.get(calls_url(world))).json()["items"]}
    assert items[str(ok)]["outcome_class"] == "completed"
    assert items[str(ok)]["task_label"] == "Appointment booking"
    assert items[str(unproven)]["outcome_class"] == "unknown"
    assert items[str(pending)]["outcome_class"] == "unknown"
    assert items[str(esc)]["outcome_class"] == "escalated"


async def test_detail_is_clinic_scoped_and_honest_about_gaps(world: World) -> None:
    sid = await add_call(world, outcome="appointment_booked", ops=[("book", "succeeded")])
    cid = world.north.id
    await add_event(sid, cid, 1, "transcript", {"speaker": "agent", "text": "Hi", "final": True})
    await add_event(
        sid, cid, 0, "transcript", {"speaker": "caller", "text": "Hello", "final": True}
    )
    await add_event(
        sid, cid, 2, "tool", {"phase": "started", "call_id": "c1", "name": "book_appointment"}
    )
    await add_event(
        sid,
        cid,
        3,
        "tool",
        {
            "phase": "finished",
            "call_id": "c1",
            "name": "book_appointment",
            "status": "rejected",
            "code": "slot_unavailable",
            "message": "That time was taken.",
            "latency_ms": 12,
            "token": "SECRET-TOKEN",
        },
    )
    d = (await world.client.get(f"{calls_url(world)}/{sid}")).json()
    assert [t["text"] for t in d["transcript"]] == ["Hello", "Hi"]
    assert d["actions"][0]["error_category"] == "scheduling_conflict"
    assert d["actions"][0]["succeeded"] is False
    assert d["outcome_class"] == "completed" and d["operations"][0]["status"] == "succeeded"
    assert d["deployment"] is None and d["evaluation"] is None
    assert d["technical"]["cost_estimate"]["available"] is False
    assert d["technical"]["cost_estimate"]["reason"] == UNAVAILABLE_NO_USAGE
    assert "SECRET-TOKEN" not in str(d)

    # Another clinic cannot read this call, and a made-up id is the same 404.
    other = f"/api/clinics/{world.lake.id}/calls/{sid}"
    assert (await world.client.get(other)).status_code == 404
    assert (await world.client.get(f"{calls_url(world)}/{uuid.uuid4()}")).status_code == 404


async def test_detail_without_transcript_or_duration(world: World) -> None:
    sid = await add_call(world, status="abandoned", duration=None)
    d = (await world.client.get(f"{calls_url(world)}/{sid}")).json()
    assert d["transcript"] == [] and d["actions"] == [] and d["duration_seconds"] is None
    assert d["outcome_class"] == "abandoned"


# ---------------------------------------------------------------------------- metrics --------
def metrics_url(world: World, name: str = "Northstar Family Medicine") -> str:
    return f"/api/clinics/{world.clinics[name].id}/call-metrics"


RANGE = {"date_from": "2026-03-03", "date_to": "2026-03-03"}


async def test_metrics_denominators_and_tenant_isolation(world: World) -> None:
    await add_call(world, outcome="appointment_booked", ops=[("book", "succeeded")])
    await add_call(world, outcome="escalated", escalation_reason="needs staff")
    await add_call(world, status="failed", error="boom", duration=None)
    await add_call(world, status="abandoned")
    await add_call(world, status="active")  # excluded from rates
    await add_call(world, "Lakeside Dermatology", outcome="information_provided")
    m = (await world.client.get(metrics_url(world), params=RANGE)).json()
    assert m["total_calls"] == 5 and m["in_progress"] == 1 and m["classified_calls"] == 4
    assert m["by_outcome"]["completed"] == 1 and m["by_outcome"]["abandoned"] == 1
    assert m["completion"]["numerator"] == 1 and m["completion"]["denominator"] == 4
    assert m["completion"]["low_sample"] is True  # fewer than ten finished calls
    assert m["escalation"]["value"] == 0.25
    assert m["calls_with_duration"] == 3 and m["average_duration_seconds"] == 60.0
    assert any("no recorded duration" in n for n in m["notes"])
    assert m["cost"]["available"] is False and m["cost"]["reason"] == UNAVAILABLE_NO_USAGE

    other = (
        await world.client.get(metrics_url(world, "Lakeside Dermatology"), params=RANGE)
    ).json()
    assert other["total_calls"] == 1


async def test_metrics_time_zone_and_empty_range(world: World) -> None:
    await add_call(world, outcome="information_provided")
    utc_day = {"date_from": "2026-03-04", "date_to": "2026-03-04"}
    m = (await world.client.get(metrics_url(world), params=utc_day)).json()
    assert m["total_calls"] == 0 and m["completion"]["value"] is None
    assert m["average_duration_seconds"] is None
    assert (await world.client.get(metrics_url(world), params=RANGE)).json()["total_calls"] == 1
    bad = await world.client.get(
        metrics_url(world), params={"date_from": "2024-01-01", "date_to": "2026-03-04"}
    )
    assert bad.status_code == 422


async def test_tool_counts_ignore_duplicates_and_pair_events(world: World) -> None:
    sid = await add_call(world, outcome="information_provided")
    cid = world.north.id
    for seq, call, status in [(1, "a", "ok"), (2, "b", "rejected"), (3, "c", "uncertain")]:
        await add_event(sid, cid, seq, "tool", {"phase": "started", "call_id": call})
        await add_event(
            sid, cid, seq + 10, "tool", {"phase": "finished", "call_id": call, "status": status}
        )
    await add_event(sid, cid, 20, "tool", {"phase": "finished", "call_id": "a", "status": "ok"})
    t = (await world.client.get(metrics_url(world), params=RANGE)).json()["tools"]
    assert (t["finished"], t["succeeded"], t["failed"], t["uncertain"]) == (3, 1, 1, 1)
    assert t["failure_rate"]["denominator"] == 3


async def test_tool_call_ids_repeating_across_calls_are_counted_separately(
    world: World,
) -> None:
    cid = world.north.id
    for _ in range(2):  # two different calls whose tools both use the id "c1"
        sid = await add_call(world, outcome="information_provided")
        await add_event(sid, cid, 1, "tool", {"phase": "finished", "call_id": "c1", "status": "ok"})
    t = (await world.client.get(metrics_url(world), params=RANGE)).json()["tools"]
    assert (t["finished"], t["succeeded"]) == (2, 2)


@pytest.fixture
def rates(tmp_path: Any) -> Any:
    import json

    from app.main import app

    path = tmp_path / "rates.json"
    path.write_text(
        json.dumps(
            {
                "currency": "USD",
                "rates": [
                    {
                        "provider": "p",
                        "model": "m",
                        "unit": "input_tokens",
                        "per": 1000,
                        "amount": "2",
                        "effective_from": "2026-01-01",
                    }
                ],
            }
        )
    )
    app.dependency_overrides[get_settings] = lambda: Settings(cost_rates_file=str(path))
    yield
    app.dependency_overrides.pop(get_settings, None)


async def test_cost_estimate_uses_recorded_usage_and_configured_rates(
    world: World, rates: None
) -> None:
    used = {"models": [{"provider": "p", "model": "m", "input_tokens": 3000}]}
    await add_call(world, outcome="information_provided", usage=used)
    await add_call(world, outcome="information_provided")  # no usage recorded
    cost = (await world.client.get(metrics_url(world), params=RANGE)).json()["cost"]
    assert cost["estimate"] is True and cost["available"] is True
    assert cost["calls_with_cost"] == 1 and cost["calls_without_cost"] == 1
    assert cost["total"] == "6.0000" and cost["currency"] == "USD"
    assert "not actual billing" in cost["note"]


async def test_cost_unavailable_for_unrated_usage(world: World) -> None:
    used = {"models": [{"provider": "x", "model": "y", "input_tokens": 10}]}
    await add_call(world, outcome="information_provided", usage=used)
    cost = (await world.client.get(metrics_url(world), params=RANGE)).json()["cost"]
    assert cost["available"] is False and cost["total"] is None


async def test_ops_routes_do_not_shadow_scheduling(world: World, client: AsyncClient) -> None:
    r = await client.get(f"/api/clinics/{world.north.id}/operations/{uuid.uuid4()}")
    assert r.status_code in (404, 401, 403, 405, 422)
