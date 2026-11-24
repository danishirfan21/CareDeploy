# Observability

What CareDeploy measures about calls, how each number is defined, and what it deliberately does not claim.

## Metrics

`GET /api/clinics/{id}/call-metrics?date_from=&date_to=` aggregates on the server (never in the browser). Default range is the last 30 days in the clinic's time zone; the maximum is one year.

Definitions:

- The range is inclusive local dates in the clinic's time zone, applied to call creation time (`[start of first day, start of the day after the last day)`). Nothing is cut at UTC midnight.
- `total_calls`: every call created in range, including in-progress calls.
- `classified_calls = total_calls - in_progress`: the denominator of every rate. Abandoned, interrupted and unknown calls count against completion and are never assumed good.
- `completion`, `escalation`, `failure`: `numerator / classified_calls`, returned with both numbers and the definition. When the denominator is 0 the value is `null`. When the denominator is under 10 the rate is flagged `low_sample` and the UI says "small sample".
- Duration: average over calls that recorded a duration, with the count used. Calls without a duration are counted in a note, not treated as zero.
- Tool counts: one per tool call (`call_id`) using the finished event. A replayed or duplicated event is not counted twice. `failed` means an error or rejection; `uncertain` is counted separately.
- Isolation: every query filters by clinic. Another clinic's calls never appear in any number.

Activity shows at most three figures (completed, escalated, average duration). The rest (outcome counts, tool counts, cost) sits behind "Show details".

## Provider usage and cost

Cost is an **estimate** and is never billing.

- Usage is whatever the voice worker recorded on the call (`provider_usage`): provider, model, input and output tokens, characters, audio seconds. Nothing is invented. A call with no usage has no cost.
- Rates come from an optional JSON file named by `COST_RATES_FILE`. Each rate has provider, model, unit, `per`, `amount`, `effective_from`, optional `effective_to` and a `source`. A call is priced with the rate in effect on the call's date. **No prices ship with CareDeploy** and none are hardcoded; without a file every cost is unavailable.
- If any metered line has no rate, the whole estimate for that call is unavailable rather than partial.
- When usage was not recorded the UI shows exactly: "Cost unavailable: provider usage data was not recorded."
- Per-call, total and per-completed-task figures use only calls that have a cost, and the counts are shown.

Rate file example:

```json
{
  "currency": "USD",
  "rates": [
    {"provider": "example", "model": "example-model", "unit": "input_tokens",
     "per": 1000, "amount": "0.00", "effective_from": "2026-01-01", "source": "your price sheet"}
  ]
}
```

(The amount above is a placeholder, not a price.)

## Redaction and logging

Event payloads and call detail are redacted by `app/ops/redact.py` (secrets, tokens, date of birth, phone) and bounded in size. Server logs carry codes and ids, not message bodies. Audio is not recorded.

## Not provided

No alerting, tracing backend, dashboards service, uptime SLOs or retention policy. No claim of HIPAA compliance or production readiness is made anywhere in the product.
