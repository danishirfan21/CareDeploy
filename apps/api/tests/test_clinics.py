import copy
import uuid
from typing import Any

import psycopg
import pytest
from httpx import AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.session import get_engine
from app.seed import LAKESIDE, NORTHSTAR, seed

DETAILS = {
    "name": "Harbor Pediatrics",
    "specialty": "Pediatrics",
    "location": "Portland, Oregon",
    "timezone": "America/Los_Angeles",
    "phone": "",
    "email": "",
}


def full_config(details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "details": details or DETAILS,
        "hours": [{"weekday": d, "opens": "08:00", "closes": "16:00"} for d in range(5)],
        "appointment_types": [{"name": "Well visit", "duration_minutes": 30}],
        "policy": {"min_notice_hours": 3, "cancellation_window_hours": 12},
        "agent": {
            "agent_name": "Harbor",
            "greeting": "Hi, Harbor Pediatrics.",
            "supported_intents": ["book_appointment"],
            "escalation_instructions": "",
            "allowed_capabilities": ["check_availability", "book_appointment"],
        },
    }


async def create(client: AsyncClient, **over: Any) -> dict[str, Any]:
    r = await client.post("/api/clinics", json={**DETAILS, **over})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


# ---- CRUD -------------------------------------------------------------------------------


async def test_clinic_crud(client: AsyncClient) -> None:
    assert (await client.get("/api/clinics")).json() == []
    c = await create(client)
    assert c["name"] == "Harbor Pediatrics" and c["latest_version"] is None

    assert [x["id"] for x in (await client.get("/api/clinics")).json()] == [c["id"]]
    assert (await client.get(f"/api/clinics/{c['id']}")).json()["timezone"] == "America/Los_Angeles"

    r = await client.patch(f"/api/clinics/{c['id']}", json={"phone": "555-0100"})
    assert r.status_code == 200
    assert r.json()["phone"] == "555-0100" and r.json()["name"] == "Harbor Pediatrics"


async def test_not_found_and_conflict_and_validation(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await client.get(f"/api/clinics/{missing}")).status_code == 404
    assert (await client.get(f"/api/clinics/{missing}/config")).status_code == 404
    assert (await client.post(f"/api/clinics/{missing}/config/publish")).status_code == 404

    c = await create(client)
    dup = await client.post("/api/clinics", json=DETAILS)
    assert dup.status_code == 409
    other = await create(client, name="Other Clinic")
    r = await client.patch(f"/api/clinics/{other['id']}", json={"name": c["name"]})
    assert r.status_code == 409

    for bad in ({"timezone": "Mars/Olympus"}, {"email": "nope"}, {"name": ""}):
        assert (await client.post("/api/clinics", json={**DETAILS, **bad})).status_code == 422
    r = await client.patch(f"/api/clinics/{c['id']}", json={"timezone": "Nowhere/Land"})
    assert r.status_code == 422


# ---- Configuration drafts -----------------------------------------------------------------


async def test_config_persists_in_database(client: AsyncClient) -> None:
    c = await create(client)
    cfg = full_config()
    r = await client.put(f"/api/clinics/{c['id']}/config", json=cfg)
    assert r.status_code == 200, r.text
    assert r.json()["has_unpublished_changes"] is True

    # Read back through the API...
    got = (await client.get(f"/api/clinics/{c['id']}/config")).json()["config"]
    assert got["hours"][0] == {"weekday": 0, "opens": "08:00", "closes": "16:00"}
    assert got["policy"]["min_notice_hours"] == 3

    # ...and directly from PostgreSQL, bypassing the API.
    url = make_url(get_settings().database_url).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(False)) as conn:
        n_hours = conn.execute(
            "SELECT count(*) FROM operating_hours WHERE clinic_id = %s", (c["id"],)
        ).fetchone()
        agent = conn.execute(
            "SELECT agent_name FROM agent_configs WHERE clinic_id = %s", (c["id"],)
        ).fetchone()
    assert n_hours == (5,) and agent == ("Harbor",)


async def test_put_config_updates_clinic_details_and_replaces_children(
    client: AsyncClient,
) -> None:
    c = await create(client)
    await client.put(f"/api/clinics/{c['id']}/config", json=full_config())
    cfg = full_config({**DETAILS, "location": "Salem, Oregon"})
    cfg["hours"] = cfg["hours"][:2]
    await client.put(f"/api/clinics/{c['id']}/config", json=cfg)
    assert (await client.get(f"/api/clinics/{c['id']}")).json()["location"] == "Salem, Oregon"
    got = (await client.get(f"/api/clinics/{c['id']}/config")).json()["config"]
    assert len(got["hours"]) == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["hours"].__setitem__(0, {"weekday": 0, "opens": "17:00", "closes": "09:00"}),
        lambda c: c["hours"].__setitem__(0, {"weekday": 0, "opens": "09:00", "closes": "09:00"}),
        lambda c: c["hours"].__setitem__(0, {"weekday": 7, "opens": "09:00", "closes": "17:00"}),
        lambda c: c["hours"].__setitem__(0, {"weekday": 0, "opens": "9am", "closes": "17:00"}),
        lambda c: c["hours"].append({"weekday": 0, "opens": "09:00", "closes": "10:00"}),
        lambda c: c["appointment_types"].append({"name": "well VISIT", "duration_minutes": 20}),
        lambda c: c["appointment_types"].append({"name": "Zero", "duration_minutes": 0}),
        lambda c: c["policy"].__setitem__("max_reschedules", -1),
        lambda c: c["agent"].__setitem__("supported_intents", ["teleport"]),
    ],
)
async def test_invalid_config_rejected_on_save(client: AsyncClient, mutate: Any) -> None:
    c = await create(client)
    cfg = full_config()
    mutate(cfg)
    r = await client.put(f"/api/clinics/{c['id']}/config", json=cfg)
    assert r.status_code == 422, r.text


# ---- Validation ---------------------------------------------------------------------------


async def test_validate_reports_issues_for_incomplete_draft(client: AsyncClient) -> None:
    c = await create(client)
    r = await client.post(f"/api/clinics/{c['id']}/config/validate")
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    errs = {(i["section"], i["message"]) for i in body["issues"] if i["severity"] == "error"}
    assert ("hours", "Select at least one operating day.") in errs
    assert any(s == "services" for s, _ in errs) and any(s == "agent" for s, _ in errs)


async def test_validate_cross_field_rules(client: AsyncClient) -> None:
    c = await create(client)
    cfg = full_config()
    cfg["appointment_types"] = [
        {"name": "Marathon", "duration_minutes": 480, "requires_human_escalation": True}
    ]
    cfg["agent"]["supported_intents"] = ["cancel_appointment", "reschedule_appointment"]
    cfg["policy"]["max_reschedules"] = 0
    cfg["hours"] = [{"weekday": 0, "opens": "09:00", "closes": "12:00"}]
    await client.put(f"/api/clinics/{c['id']}/config", json=cfg)
    msgs = [
        i["message"]
        for i in (await client.post(f"/api/clinics/{c['id']}/config/validate")).json()["issues"]
        if i["severity"] == "error"
    ]
    joined = " | ".join(msgs)
    assert "longer than any operating day" in joined
    assert "needs the 'cancel_appointment' capability" in joined
    assert "0 reschedules" in joined
    assert "escalation instructions" in joined and "escalate_to_human" in joined


# ---- Publishing & immutability ------------------------------------------------------------


async def test_publish_creates_immutable_versions(client: AsyncClient) -> None:
    c = await create(client)
    cid = c["id"]

    # Invalid draft cannot be published.
    r = await client.post(f"/api/clinics/{cid}/config/publish")
    assert r.status_code == 422 and r.json()["detail"]["valid"] is False

    await client.put(f"/api/clinics/{cid}/config", json=full_config())
    r = await client.post(f"/api/clinics/{cid}/config/publish")
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 1

    state = (await client.get(f"/api/clinics/{cid}/config")).json()
    assert state["latest_version"] == 1 and state["has_unpublished_changes"] is False
    assert (await client.get(f"/api/clinics/{cid}")).json()["latest_version"] == 1

    # Publishing an unchanged draft is a conflict, not a duplicate version.
    assert (await client.post(f"/api/clinics/{cid}/config/publish")).status_code == 409

    # Editing the draft does not alter the published version.
    edited = full_config()
    edited["agent"]["greeting"] = "A brand new greeting."
    await client.put(f"/api/clinics/{cid}/config", json=edited)
    v1 = (await client.get(f"/api/clinics/{cid}/versions/1")).json()
    assert v1["config"]["agent"]["greeting"] == "Hi, Harbor Pediatrics."
    assert (await client.get(f"/api/clinics/{cid}/config")).json()["has_unpublished_changes"]

    assert (await client.post(f"/api/clinics/{cid}/config/publish")).json()["version"] == 2
    versions = (await client.get(f"/api/clinics/{cid}/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert (await client.get(f"/api/clinics/{cid}/versions/9")).status_code == 404


async def test_database_blocks_modifying_published_versions(client: AsyncClient) -> None:
    c = await create(client)
    await client.put(f"/api/clinics/{c['id']}/config", json=full_config())
    await client.post(f"/api/clinics/{c['id']}/config/publish")

    url = make_url(get_settings().database_url).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(False), autocommit=True) as conn:
        for sql in (
            "UPDATE config_versions SET snapshot = '{}'::jsonb",
            "UPDATE config_versions SET version = 99",
            "DELETE FROM config_versions",
        ):
            with pytest.raises(psycopg.errors.RestrictViolation, match="immutable"):
                conn.execute(sql)
        assert conn.execute("SELECT count(*) FROM config_versions").fetchone() == (1,)


# ---- Isolation & seeds --------------------------------------------------------------------


async def test_clinic_isolation(client: AsyncClient) -> None:
    a = await create(client, name="Clinic A")
    b = await create(client, name="Clinic B")
    cfg_a = full_config({**DETAILS, "name": "Clinic A"})
    cfg_b = copy.deepcopy(cfg_a)
    cfg_b["details"]["name"] = "Clinic B"
    cfg_b["hours"] = [{"weekday": 6, "opens": "12:00", "closes": "13:00"}]
    cfg_b["appointment_types"] = [{"name": "Only B", "duration_minutes": 10}]
    cfg_b["agent"]["agent_name"] = "Bee"
    await client.put(f"/api/clinics/{a['id']}/config", json=cfg_a)
    await client.put(f"/api/clinics/{b['id']}/config", json=cfg_b)
    await client.post(f"/api/clinics/{a['id']}/config/publish")

    got_a = (await client.get(f"/api/clinics/{a['id']}/config")).json()["config"]
    got_b = (await client.get(f"/api/clinics/{b['id']}/config")).json()
    assert got_a["agent"]["agent_name"] == "Harbor" and len(got_a["hours"]) == 5
    assert got_b["config"]["agent"]["agent_name"] == "Bee"
    assert [t["name"] for t in got_b["config"]["appointment_types"]] == ["Only B"]
    assert got_b["latest_version"] is None
    assert (await client.get(f"/api/clinics/{b['id']}/versions")).json() == []
    assert len((await client.get(f"/api/clinics/{a['id']}/versions")).json()) == 1


async def test_seed_creates_two_distinct_clinics_idempotently(client: AsyncClient) -> None:
    sessionmaker = async_sessionmaker(get_engine())
    async with sessionmaker() as s:
        assert len(await seed(s)) == 2
    async with sessionmaker() as s:
        assert await seed(s) == []

    clinics = {c["name"]: c for c in (await client.get("/api/clinics")).json()}
    assert set(clinics) == {"Northstar Family Medicine", "Lakeside Dermatology"}
    north = (
        await client.get(f"/api/clinics/{clinics['Northstar Family Medicine']['id']}/config")
    ).json()["config"]
    lake = (
        await client.get(f"/api/clinics/{clinics['Lakeside Dermatology']['id']}/config")
    ).json()["config"]
    assert north["details"]["timezone"] == "America/Chicago"
    assert lake["details"]["timezone"] == "America/Denver"
    assert [h["weekday"] for h in north["hours"]] == [0, 1, 2, 3, 4]
    assert [h["weekday"] for h in lake["hours"]] == [1, 2, 3, 4, 5]
    assert {t["duration_minutes"] for t in north["appointment_types"]} == {30}
    assert len({t["duration_minutes"] for t in lake["appointment_types"]}) > 1
    assert any(t["requires_human_escalation"] for t in lake["appointment_types"])
    assert not any(t["requires_human_escalation"] for t in north["appointment_types"])
    # Seeds are publishable as-is.
    for name in (NORTHSTAR, LAKESIDE):
        cid = clinics[name.details.name]["id"]
        assert (await client.post(f"/api/clinics/{cid}/config/validate")).json()["valid"] is True
