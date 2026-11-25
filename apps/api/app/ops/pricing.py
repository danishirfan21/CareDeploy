"""Provider usage and cost estimation (M5).

Usage comes from what the voice worker recorded in `call_sessions.provider_usage` (the model
usage the LiveKit agent framework metered). Nothing is invented: a call with no recorded usage has
no cost, and a metered line with no configured rate makes the whole estimate unavailable rather
than partial. Prices are never built in. They come from a rate file the operator owns, each with
an effective date range and a source note. Figures are estimates and are not Karing's, or anyone's,
actual operating costs.

Rate file (JSON), see docs/observability.md:

    {"currency": "USD", "rates": [
      {"provider": "...", "model": "...", "unit": "input_tokens", "per": 1000000,
       "amount": "0.00", "effective_from": "2026-01-01", "effective_to": null,
       "source": "where this number came from"}]}

Units: input_tokens, output_tokens, characters, audio_seconds. Amounts are decimal strings.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

log = logging.getLogger("caredeploy.pricing")
UNITS = ("input_tokens", "output_tokens", "characters", "audio_seconds")
UNAVAILABLE_NO_USAGE = "Cost unavailable: provider usage data was not recorded."
# livekit-agents usage field -> our unit
_FIELD_UNIT = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "characters_count": "characters",
    "audio_duration": "audio_seconds",
}


@dataclass(frozen=True)
class Rate:
    provider: str
    model: str
    unit: str
    per: Decimal
    amount: Decimal
    effective_from: date
    effective_to: date | None
    source: str


@dataclass(frozen=True)
class RateTable:
    currency: str
    rates: tuple[Rate, ...]

    def find(self, provider: str, model: str, unit: str, on: date) -> Rate | None:
        for r in self.rates:
            if (
                r.provider == provider
                and r.model == model
                and r.unit == unit
                and r.effective_from <= on
                and (r.effective_to is None or on <= r.effective_to)
            ):
                return r
        return None


EMPTY = RateTable("USD", ())


def load_rates(path: str) -> RateTable:
    """Read the rate file. No path means no pricing is configured. A file that is missing,
    unreadable or invalid is treated the same way (every cost is unavailable) and logged: a
    broken price list must never produce a wrong number or break the call pages."""
    if not path:
        return EMPTY
    file = Path(path)
    if not file.is_file():
        log.warning("COST_RATES_FILE is set but the file does not exist; costs are unavailable")
        return EMPTY
    try:
        return parse_rates(json.loads(file.read_text(encoding="utf8")))
    except (ValueError, KeyError, TypeError, InvalidOperation, OSError) as exc:
        log.warning("COST_RATES_FILE is invalid (%s); costs are unavailable", exc)
        return EMPTY


def parse_rates(data: dict[str, Any]) -> RateTable:
    """Parse and validate. Raises ValueError for anything that could price a call wrongly:
    unknown unit, non-positive `per`, negative amount, an end date before the start date, or two
    rates for the same provider, model and unit whose dates overlap."""
    rates: list[Rate] = []
    for r in data.get("rates", []):
        if r["unit"] not in UNITS:
            raise ValueError(f"unknown pricing unit {r['unit']!r}")
        rate = Rate(
            provider=str(r["provider"]),
            model=str(r["model"]),
            unit=str(r["unit"]),
            per=Decimal(str(r["per"])),
            amount=Decimal(str(r["amount"])),
            effective_from=date.fromisoformat(r["effective_from"]),
            effective_to=date.fromisoformat(r["effective_to"]) if r.get("effective_to") else None,
            source=str(r.get("source", "")),
        )
        label = f"{rate.provider}/{rate.model} {rate.unit}"
        if not rate.per.is_finite() or rate.per <= 0:
            raise ValueError(f"{label}: 'per' must be a positive number")
        if not rate.amount.is_finite() or rate.amount < 0:
            raise ValueError(f"{label}: 'amount' must not be negative")
        if rate.effective_to is not None and rate.effective_to < rate.effective_from:
            raise ValueError(f"{label}: effective_to is before effective_from")
        for other in rates:
            if (other.provider, other.model, other.unit) != (rate.provider, rate.model, rate.unit):
                continue
            a_end = other.effective_to or date.max
            b_end = rate.effective_to or date.max
            if rate.effective_from <= a_end and other.effective_from <= b_end:
                raise ValueError(f"{label}: overlapping effective date ranges")
        rates.append(rate)
    currency = str(data.get("currency", "USD")).strip()
    if not currency:
        raise ValueError("currency must not be empty")
    return RateTable(currency, tuple(rates))


def metered_lines(provider_usage: dict[str, Any]) -> list[dict[str, Any]]:
    """The measured quantities in a call's stored usage, one per provider, model and unit."""
    out: list[dict[str, Any]] = []
    models = provider_usage.get("models") if isinstance(provider_usage, dict) else None
    if not isinstance(models, list):
        return out
    for m in models:
        if not isinstance(m, dict):
            continue
        provider, model = m.get("provider"), m.get("model")
        if not provider or not model:
            continue
        for fieldname, unit in _FIELD_UNIT.items():
            qty = m.get(fieldname)
            if isinstance(qty, int | float) and not isinstance(qty, bool) and qty > 0:
                out.append(
                    {
                        "provider": str(provider),
                        "model": str(model),
                        "unit": unit,
                        "quantity": float(qty),
                    }
                )
    return out


def estimate(
    provider_usage: dict[str, Any],
    when: datetime,
    table: RateTable,
    calculated_at: datetime | None = None,
) -> dict[str, Any]:
    """Estimate one call. `available` is true only when every metered line has a rate."""
    lines = metered_lines(provider_usage)
    base: dict[str, Any] = {
        "available": False,
        "estimate": True,
        "currency": table.currency,
        "amount": None,
        "lines": [],
        "reason": None,
        "calculated_at": (calculated_at or datetime.now(UTC)).isoformat(),
    }
    if not lines:
        base["reason"] = UNAVAILABLE_NO_USAGE
        return base
    on = when.astimezone(UTC).date()
    total = Decimal(0)
    missing: list[str] = []
    for line in lines:
        rate = table.find(line["provider"], line["model"], line["unit"], on)
        if rate is None:
            missing.append(f"{line['provider']}/{line['model']} {line['unit']}")
            base["lines"].append({**line, "rate": None, "amount": None})
            continue
        amount = Decimal(str(line["quantity"])) / rate.per * rate.amount
        total += amount
        base["lines"].append(
            {
                **line,
                "rate": {
                    "per": str(rate.per),
                    "amount": str(rate.amount),
                    "effective_from": rate.effective_from.isoformat(),
                    "effective_to": rate.effective_to.isoformat() if rate.effective_to else None,
                    "source": rate.source,
                },
                "amount": str(amount.quantize(Decimal("0.000001"))),
            }
        )
    if missing:
        base["reason"] = (
            "Cost unavailable: no pricing rate is configured for " + ", ".join(missing) + "."
        )
        return base
    base["available"] = True
    base["amount"] = str(total.quantize(Decimal("0.000001")))
    return base
