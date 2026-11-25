"""Outcome classification: a pure function of the call record and the operations ledger."""

from pathlib import Path
from typing import Any

import pytest

from app.ops.classify import LedgerOp, classify, error_category
from app.ops.pricing import UNAVAILABLE_NO_USAGE, RateTable, estimate, parse_rates
from app.ops.redact import scrub


def run(**over: Any) -> Any:
    base: dict[str, Any] = {
        "status": "completed",
        "outcome": None,
        "escalation_reason": None,
        "error": None,
        "transport_lost": False,
        "ops": [],
    }
    base.update(over)
    return classify(**base)


def op(kind: str, status: str) -> LedgerOp:
    return LedgerOp("op-1", kind, status)


def test_in_progress_has_no_class() -> None:
    assert run(status="active").outcome_class is None
    assert run(status="created").outcome_class is None


@pytest.mark.parametrize(
    ("outcome", "kind"),
    [
        ("appointment_booked", "book"),
        ("appointment_rescheduled", "reschedule"),
        ("appointment_cancelled", "cancel"),
    ],
)
def test_scheduling_completes_only_when_ledger_committed(outcome: str, kind: str) -> None:
    assert run(outcome=outcome, ops=[op(kind, "succeeded")]).outcome_class == "completed"
    # Friendly closing wording is not evidence.
    assert run(outcome=outcome, ops=[]).outcome_class == "unknown"
    assert run(outcome=outcome, ops=[op(kind, "failed")]).outcome_class == "failed"
    assert run(outcome=outcome, ops=[op(kind, "aborted")]).outcome_class == "failed"
    assert run(outcome=outcome, ops=[op(kind, "processing")]).outcome_class == "unknown"


def test_wrong_operation_type_does_not_count() -> None:
    r = run(outcome="appointment_booked", ops=[op("cancel", "succeeded")])
    assert r.outcome_class == "unknown"


def test_unresolved_ledger_is_unknown_even_after_escalation() -> None:
    r = run(outcome="escalated", ops=[op("book", "processing")])
    assert r.outcome_class == "unknown"


def test_escalation_is_not_failure() -> None:
    assert run(outcome="escalated").outcome_class == "escalated"
    assert run(escalation_reason="caller asked for a person").outcome_class == "escalated"


def test_failures() -> None:
    assert run(status="failed", error="connection_failed").outcome_class == "failed"
    assert run(outcome="failed").outcome_class == "failed"
    assert run(ops=[op("book", "failed")]).outcome_class == "failed"


def test_information_only_is_completed_with_task() -> None:
    r = run(outcome="information_provided")
    assert (r.outcome_class, r.task_type) == ("completed", "information")


def test_abandoned_and_interrupted() -> None:
    assert run(status="abandoned").outcome_class == "abandoned"
    assert run(outcome="no_action").outcome_class == "abandoned"
    assert run(transport_lost=True).outcome_class == "interrupted"


def test_task_type_is_unset_when_not_identifiable() -> None:
    assert run(status="abandoned").task_type is None


def test_error_categories() -> None:
    assert error_category("committed", None) is None
    assert error_category("needs_input", None) is None
    assert error_category("uncertain", "outcome_unknown") == "unknown_outcome"
    assert error_category("rejected", "slot_unavailable") == "scheduling_conflict"
    assert error_category("error", "dependency_unavailable") == "infrastructure"
    assert error_category("error", "something_new") == "other"


def test_scrub_drops_secrets_recursively() -> None:
    out = scrub({"a": 1, "token": "x", "n": [{"api_key": "k", "ok": True}], "DOB": "1990"})
    assert out == {"a": 1, "n": [{"ok": True}]}
    assert "token" not in str(out) and "api_key" not in str(out)


# ------------------------------------------------------------------------------ pricing ------
def table() -> RateTable:
    return parse_rates(
        {
            "currency": "USD",
            "rates": [
                {
                    "provider": "p",
                    "model": "m",
                    "unit": "input_tokens",
                    "per": 1000,
                    "amount": "0.5",
                    "effective_from": "2026-01-01",
                },
                {
                    "provider": "p",
                    "model": "m",
                    "unit": "output_tokens",
                    "per": 1000,
                    "amount": "1.5",
                    "effective_from": "2026-01-01",
                },
            ],
        }
    )


def usage(**over: Any) -> dict[str, Any]:
    row = {"provider": "p", "model": "m", "input_tokens": 2000, "output_tokens": 1000}
    row.update(over)
    return {"models": [row]}


def test_cost_unavailable_without_usage() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 1, tzinfo=UTC)
    est = estimate({}, now, table(), now)
    assert est["available"] is False and est["reason"] == UNAVAILABLE_NO_USAGE
    assert UNAVAILABLE_NO_USAGE == "Cost unavailable: provider usage data was not recorded."


def test_cost_is_computed_from_rates_and_dated() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 1, tzinfo=UTC)
    est = estimate(usage(), now, table(), now)
    assert est["available"] and est["estimate"] is True
    assert float(est["amount"]) == pytest.approx(2.5)
    # Before the rate took effect there is no applicable rate: unavailable, never guessed.
    early = datetime(2025, 6, 1, tzinfo=UTC)
    assert estimate(usage(), early, table(), now)["available"] is False
    # An unrated metered line makes the whole estimate unavailable.
    assert estimate(usage(characters_count=500), now, table(), now)["available"] is False


# --------------------------------------------------------------------- rate file validation ----
def _rate(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "provider": "p",
        "model": "m",
        "unit": "input_tokens",
        "per": 1000,
        "amount": "0.5",
        "effective_from": "2026-01-01",
    }
    base.update(over)
    return base


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ({"unit": "dollars"}, "unknown pricing unit"),
        ({"per": 0}, "positive"),
        ({"per": -1000}, "positive"),
        ({"amount": "-0.1"}, "negative"),
        ({"effective_to": "2025-12-31"}, "before effective_from"),
        ({"per": "NaN"}, "positive"),
    ],
)
def test_invalid_rates_are_rejected(bad: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_rates({"rates": [_rate(**bad)]})


def test_overlapping_rates_are_rejected_but_adjacent_ranges_are_allowed() -> None:
    with pytest.raises(ValueError, match="overlapping"):
        parse_rates({"rates": [_rate(), _rate(effective_from="2026-06-01")]})
    ok = parse_rates(
        {
            "rates": [
                _rate(effective_to="2026-05-31"),
                _rate(effective_from="2026-06-01", amount="0.6"),
            ]
        }
    )
    assert len(ok.rates) == 2


def test_broken_rate_file_means_no_pricing_not_a_crash(tmp_path: Path) -> None:
    from app.ops.pricing import EMPTY, load_rates

    bad = tmp_path / "rates.json"
    bad.write_text('{"rates": [{"provider": "p"}]}', encoding="utf8")
    assert load_rates(str(bad)) is EMPTY
    bad.write_text("not json", encoding="utf8")
    assert load_rates(str(bad)) is EMPTY
    assert load_rates(str(tmp_path / "missing.json")) is EMPTY
    assert load_rates("") is EMPTY
