"""Call outcome classification (M5).

The agent reports an `outcome` (M3). That is a claim, not proof: a friendly closing sentence does
not mean an appointment changed. The domain classification below is what the evidence supports.

* completed   - the supported task reached a verified terminal result. A booking, reschedule or
                cancellation counts only when the operations ledger shows a `succeeded`
                operation of that type. Answering a question without changing anything also
                counts (the task was information, and nothing needed verifying).
* escalated   - the caller was handed to staff. Often correct behavior, never counted as failure.
* failed      - the call or the requested change ended in an error, or the ledger shows the
                operation failed or was aborted.
* abandoned   - the caller left (or the room was never joined) before any task finished.
* interrupted - the connection was lost before the call could finish.
* unknown     - the ledger cannot say whether a change committed (still `processing`), or the
                agent claims a change the ledger does not show. Never treated as success.

`None` means the call is still in progress. Historical M3 rows are classified lazily from the
same inputs, so they need no special handling.
"""

from dataclasses import dataclass

CLAIMED_OPERATION = {
    "appointment_booked": "book",
    "appointment_rescheduled": "reschedule",
    "appointment_cancelled": "cancel",
}
TASK_OF_OPERATION = {"book": "booking", "reschedule": "reschedule", "cancel": "cancellation"}
TASK_LABELS = {
    "booking": "Appointment booking",
    "reschedule": "Appointment reschedule",
    "cancellation": "Appointment cancellation",
    "information": "Information request",
}
CLASS_LABELS = {
    "completed": "Completed",
    "escalated": "Escalated",
    "failed": "Failed",
    "abandoned": "Abandoned",
    "interrupted": "Interrupted",
    "unknown": "Unknown",
}
TERMINAL_STATUSES = {"completed", "failed", "abandoned"}


@dataclass(frozen=True)
class LedgerOp:
    id: str
    operation_type: str  # book | reschedule | cancel
    status: str  # processing | succeeded | failed | aborted


@dataclass(frozen=True)
class Classification:
    outcome_class: str | None
    task_type: str | None
    reason: str


def classify(
    *,
    status: str,
    outcome: str | None,
    escalation_reason: str | None,
    error: str | None,
    transport_lost: bool,
    ops: list[LedgerOp],
) -> Classification:
    if status not in TERMINAL_STATUSES:
        return Classification(None, None, "The call has not ended.")

    claimed = CLAIMED_OPERATION.get(outcome or "")
    task: str | None
    if claimed:
        task = TASK_OF_OPERATION[claimed]
    elif ops:
        task = TASK_OF_OPERATION.get(ops[-1].operation_type)
    elif outcome == "information_provided":
        task = "information"
    else:
        task = None

    if any(o.status == "processing" for o in ops):
        return Classification(
            "unknown", task, "A scheduling change was still processing; its outcome is unresolved."
        )

    if claimed:
        matching = [o for o in ops if o.operation_type == claimed]
        if any(o.status == "succeeded" for o in matching):
            return Classification("completed", task, "The operations ledger shows it committed.")
        if matching:
            return Classification(
                "failed", task, "The operation did not commit (ledger: failed or aborted)."
            )
        return Classification(
            "unknown",
            task,
            "The agent reported a change but the operations ledger has no matching operation.",
        )

    if outcome == "escalated" or escalation_reason:
        return Classification("escalated", task, "The caller was referred to clinic staff.")
    if status == "failed" or outcome == "failed":
        return Classification("failed", task, error or "The call ended with an error.")
    if outcome == "information_provided":
        return Classification("completed", "information", "Information was provided.")
    if any(o.status in ("failed", "aborted") for o in ops):
        return Classification("failed", task, "A requested change did not commit.")
    if transport_lost:
        return Classification("interrupted", task, "The connection was lost before the call ended.")
    return Classification("abandoned", task, "The call ended without a completed task.")


# --------------------------------------------------------------------------- tool errors ------
# Deterministic categories from the tool result status and code. No model involved.
_CODE_CATEGORY = {
    "slot_unavailable": "scheduling_conflict",
    "conflict": "scheduling_conflict",
    "slot_taken": "scheduling_conflict",
    "outside_hours": "policy_rejection",
    "policy_violation": "policy_rejection",
    "outside_booking_window": "policy_rejection",
    "too_soon": "policy_rejection",
    "verification_required": "authorization",
    "verification_failed": "authorization",
    "verification_locked": "authorization",
    "ambiguous_patient": "authorization",
    "forbidden": "authorization",
    "awaiting_caller_confirmation": "confirmation",
    "confirmation_not_heard": "confirmation",
    "outcome_unknown": "unknown_outcome",
    "invalid_arguments": "validation",
    "unknown_slot_ref": "validation",
    "unknown_appointment_ref": "validation",
    "slot_type_mismatch": "validation",
    "appointment_type_ambiguous": "validation",
    "no_operation": "validation",
    "unknown_tool": "validation",
    "human_escalation_required": "escalation",
    "escalation_recorded": "escalation",
    "dependency_unavailable": "infrastructure",
    "internal_error": "internal",
    "appointment_modified": "scheduling_conflict",
    "operation_in_progress": "scheduling_conflict",
    "operation_expired": "confirmation",
    "proposal_already_used": "confirmation",
    "proposal_mismatch": "confirmation",
    "proposal_not_confirmed": "confirmation",
    "authentication_required": "authorization",
    "authorization_expired": "authorization",
    "idempotency_conflict": "validation",
    "invalid_input": "validation",
    "invalid_state_transition": "validation",
    "not_found": "validation",
    "clinic_not_configured": "validation",
    "scheduling_error": "internal",
}
CATEGORY_LABELS = {
    "scheduling_conflict": "Scheduling conflict",
    "policy_rejection": "Policy rejection",
    "authorization": "Verification or authorization",
    "confirmation": "Confirmation required",
    "unknown_outcome": "Unknown outcome",
    "validation": "Invalid request",
    "escalation": "Escalation",
    "infrastructure": "Backend unavailable",
    "internal": "Internal error",
    "other": "Other",
}
OK_STATUSES = {"ok", "committed", "needs_input"}


def error_category(status: str | None, code: str | None) -> str | None:
    """None for a tool call that did what was asked; otherwise a stable category."""
    if status in OK_STATUSES:
        return None
    if status == "uncertain":
        return "unknown_outcome"
    if code and code in _CODE_CATEGORY:
        return _CODE_CATEGORY[code]
    return "other"
