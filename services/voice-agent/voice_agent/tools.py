"""Scheduling tools the LLM may call. They are a typed façade over the M2 API: no scheduling
rule lives here. What lives here is the *call discipline*:

* arguments are validated; the model never supplies ids, only refs the tools handed out earlier
  (``S1`` slots, ``A1`` appointments), so it cannot invent or cross-wire clinic data;
* every request is scoped to the call's clinic and to the verified patient's bearer token;
* a state-changing request needs a caller turn *after* the proposal, quoted back by the model;
* results distinguish ``committed`` / ``rejected`` / ``uncertain``; a timeout is never a failure
  and never a success: it is reconciled through the backend's operation records using the SAME
  idempotency key, never a new one.
"""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from voice_agent.contracts import AppointmentTypeInfo, CallContext
from voice_agent.events import EventRecorder
from voice_agent.scheduling_client import ApiResult, SchedulingClient
from voice_agent.states import Conversation, Operation, StateTracker

log = logging.getLogger("voice_agent.tools")

Status = Literal["ok", "needs_input", "committed", "rejected", "uncertain", "error"]

CAPABILITY_FOR_TOOL = {
    "get_appointment_availability": "check_availability",
    "propose_booking": "book_appointment",
    "propose_reschedule": "reschedule_appointment",
    "propose_cancellation": "cancel_appointment",
    "request_human_escalation": "escalate_to_human",
}
NEEDS_VERIFIED_PATIENT = {
    "get_patient_appointments",
    "propose_booking",
    "propose_reschedule",
    "propose_cancellation",
}
OUTCOME_FOR_ACTION = {
    "book": "appointment_booked",
    "reschedule": "appointment_rescheduled",
    "cancel": "appointment_cancelled",
}

REJECTION_GUIDANCE = {
    "slot_unavailable": "That time was just taken. Check availability again and offer other times.",
    "operation_expired": "The proposal expired. Propose it again and re-confirm with the caller.",
    "proposal_mismatch": "The details changed after the proposal. Propose again and re-confirm.",
    "proposal_not_confirmed": "The caller's confirmation was not recorded. Propose again.",
    "proposal_already_used": "That proposal was already used. Check get_operation_status.",
    "policy_violation": "Explain the clinic policy using the message; offer an alternative.",
    "authorization_expired": "Verification expired. Verify the caller again.",
    "authentication_required": "Verify the caller first.",
    "invalid_state_transition": "That appointment can no longer be changed that way.",
    "appointment_modified": "The appointment changed meanwhile. Fetch appointments again.",
}


class ToolResult(BaseModel):
    ok: bool
    status: Status
    message: str = ""
    code: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    operation_id: str | None = None
    guidance: str = ""

    def for_llm(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "message": self.message}
        if self.code:
            out["error_code"] = self.code
        if self.data:
            out["data"] = self.data
        if self.guidance:
            out["next_step"] = self.guidance
        return out


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClinicInfoArgs(_Args):
    topic: Literal["hours", "services", "policies", "location", "contact", "all"] = "all"


class AvailabilityArgs(_Args):
    appointment_type: str = Field(min_length=1, max_length=100)
    date_from: date
    date_to: date | None = None
    max_results: int = Field(default=3, ge=1, le=5)


class VerifyArgs(_Args):
    patient_name: str = Field(min_length=2, max_length=100)
    date_of_birth: date
    phone_last4: str = Field(pattern=r"^\d{4}$")


class NoArgs(_Args):
    pass


class ProposeBookArgs(_Args):
    appointment_type: str = Field(min_length=1, max_length=100)
    slot_ref: str = Field(pattern=r"^S\d{1,4}$")


class ProposeRescheduleArgs(_Args):
    appointment_ref: str = Field(pattern=r"^A\d{1,3}$")
    slot_ref: str = Field(pattern=r"^S\d{1,4}$")


class ProposeCancelArgs(_Args):
    appointment_ref: str = Field(pattern=r"^A\d{1,3}$")
    reason: str | None = Field(default=None, max_length=200)


class ConfirmArgs(_Args):
    caller_words: str = Field(min_length=1, max_length=300)


class WithdrawArgs(_Args):
    reason: str | None = Field(default=None, max_length=200)


class EscalateArgs(_Args):
    reason: str = Field(min_length=3, max_length=300)


@dataclass
class Pending:
    proposal_id: uuid.UUID
    confirmation_token: str
    action: Literal["book", "reschedule", "cancel"]
    summary: str
    key: str
    start_at: str | None
    appointment_type_id: uuid.UUID | None
    appointment_id: str | None
    reason: str | None
    turns_at_proposal: int
    confirmed: bool = False
    operation_id: str | None = None


@dataclass
class Metrics:
    tool_calls: int = 0
    tool_failures: int = 0
    by_tool: dict[str, int] = field(default_factory=dict)
    committed: int = 0
    rejected: int = 0
    uncertain: int = 0
    latencies_ms: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        lat = sorted(self.latencies_ms)
        return {
            "tool_calls": self.tool_calls,
            "tool_failures": self.tool_failures,
            "tool_calls_by_name": dict(self.by_tool),
            "operations_committed": self.committed,
            "operations_rejected": self.rejected,
            "operations_uncertain": self.uncertain,
            "tool_latency_ms": {
                "count": len(lat),
                "max": lat[-1] if lat else None,
                "median": lat[len(lat) // 2] if lat else None,
            },
        }


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def speak_time(local_iso: str) -> str:
    dt = datetime.fromisoformat(local_iso)
    day = dt.day
    suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{dt.strftime('%A, %B')} {day}{suffix} at {dt.strftime('%I:%M %p').lstrip('0')}"


class Toolbox:
    def __init__(
        self,
        ctx: CallContext,
        client: SchedulingClient,
        recorder: EventRecorder,
        tracker: StateTracker,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        reconcile_attempts: int = 3,
    ) -> None:
        self.ctx, self.client, self.rec, self.tracker = ctx, client, recorder, tracker
        self._clock, self._sleep, self._attempts = clock, sleep, reconcile_attempts
        self.metrics = Metrics()
        self.user_turns: list[str] = []
        self.patient_id: uuid.UUID | None = None
        self.patient_name: str | None = None
        self._auth: str | None = None
        self._verify_failures = 0
        self.slots: dict[str, dict[str, Any]] = {}
        self.appts: dict[str, dict[str, Any]] = {}
        self.pending: Pending | None = None
        self.last_unknown: Pending | None = None
        self.committed: list[dict[str, Any]] = []
        self.operation_ids: list[str] = []
        self.escalation_reason: str | None = None
        self.used_information_tools = False
        self._n = 0

    # ---------------------------------------------------------------- bookkeeping --------------
    def note_user_turn(self, text: str) -> None:
        """Called for every *final* caller utterance (never for interim fragments)."""
        if text.strip():
            self.user_turns.append(text)

    @property
    def verified(self) -> bool:
        return self._auth is not None

    def outcome(self) -> str:
        if self.committed:
            return OUTCOME_FOR_ACTION[self.committed[-1]["action"]]
        if self.escalation_reason:
            return "escalated"
        if self.used_information_tools:
            return "information_provided"
        return "no_action"

    def tool_names(self) -> list[str]:
        return sorted(CAPABILITY_FOR_TOOL) + [
            "get_clinic_information",
            "verify_patient",
            "get_patient_appointments",
            "confirm_operation",
            "get_operation_status",
            "withdraw_pending_proposal",
        ]

    # ---------------------------------------------------------------- dispatcher --------------
    async def call(self, name: str, raw: dict[str, Any]) -> ToolResult:
        """Validate, gate by capability, run, record, classify. Never raises."""
        self._n += 1
        call_id = f"t{self._n}"
        spec = _SPECS.get(name)
        started = time.perf_counter()
        self.rec.record(
            "tool",
            {"call_id": call_id, "name": name, "phase": "started", "args": raw},
            event_id=f"tool:{call_id}:started",
        )
        prior_conv = self.tracker.conversation
        self.tracker.set_conversation(Conversation.EXECUTING_TOOL)
        try:
            if spec is None:
                result = _err("unknown_tool", f"There is no tool named {name}.")
            else:
                model, method = spec
                handler = getattr(self, method)
                try:
                    args = model.model_validate(raw)
                except ValidationError as e:
                    result = _invalid(e)
                else:
                    result = await self._gated(name, handler, args)
        except Exception:
            log.exception("tool %s crashed", name)
            result = _err(
                "internal_error",
                "That lookup failed unexpectedly.",
                guidance=("Apologize briefly and offer to try again or hand off to staff."),
            )
        elapsed = int((time.perf_counter() - started) * 1000)
        self.metrics.tool_calls += 1
        self.metrics.by_tool[name] = self.metrics.by_tool.get(name, 0) + 1
        self.metrics.latencies_ms.append(elapsed)
        if result.status in ("error", "rejected"):
            self.metrics.tool_failures += 1
        if result.operation_id and result.operation_id not in self.operation_ids:
            self.operation_ids.append(result.operation_id)
        self.rec.record(
            "tool",
            {
                "call_id": call_id,
                "name": name,
                "phase": "finished",
                "status": result.status,
                "code": result.code,
                "message": result.message,
                "operation_id": result.operation_id,
                "latency_ms": elapsed,
            },
            event_id=f"tool:{call_id}:finished",
        )
        if self.tracker.conversation == Conversation.EXECUTING_TOOL:
            self.tracker.set_conversation(self._resting_state(prior_conv))
        return result

    def _resting_state(self, prior: Conversation) -> Conversation:
        if self.escalation_reason:
            return Conversation.ESCALATED
        if self.pending and not self.pending.confirmed:
            return Conversation.AWAITING_CONFIRMATION
        if self.last_unknown:
            return Conversation.RECOVERING
        return (
            Conversation.THINKING
            if prior in (Conversation.THINKING, Conversation.EXECUTING_TOOL)
            else prior
        )

    async def _gated(
        self, name: str, handler: Callable[[Any], Awaitable[ToolResult]], args: Any
    ) -> ToolResult:
        cap = CAPABILITY_FOR_TOOL.get(name)
        if cap and not self.ctx.can(cap):
            return _err(
                "capability_not_enabled",
                "This clinic has not enabled that capability for the voice agent.",
                guidance="Tell the caller you can't do that here and offer a human hand-off.",
            )
        if name == "get_clinic_information" and not self.ctx.supports("clinic_information"):
            return _err(
                "capability_not_enabled",
                "This clinic has not enabled clinic information for the voice agent.",
                guidance="Offer a human hand-off for that question.",
            )
        if name in NEEDS_VERIFIED_PATIENT and not self.verified:
            self.tracker.set_conversation(Conversation.WAITING_VERIFICATION)
            return ToolResult(
                ok=False,
                status="needs_input",
                code="verification_required",
                message="The caller has not been verified yet.",
                guidance="Ask for full name, date of birth and last four digits of the phone "
                "number, then call verify_patient.",
            )
        return await handler(args)

    # ---------------------------------------------------------------- helpers -----------------
    def _resolve_type(self, text: str) -> AppointmentTypeInfo | ToolResult:
        types = self.ctx.config.appointment_types
        q = text.strip().lower()
        exact = [t for t in types if t.name.lower() == q]
        found = exact or [t for t in types if q in t.name.lower() or t.name.lower() in q]
        if len(found) == 1:
            return found[0]
        names = ", ".join(t.name for t in types)
        return ToolResult(
            ok=False,
            status="needs_input",
            code="appointment_type_ambiguous" if found else "appointment_type_unknown",
            message=f"Which appointment type? This clinic offers: {names}.",
            guidance="Ask the caller to choose one of the listed types.",
        )

    def _api_failure(self, r: ApiResult) -> ToolResult:
        if r.kind == "unavailable":
            return ToolResult(
                ok=False,
                status="error",
                code=r.code or "unavailable",
                message="The scheduling system is not responding right now.",
                guidance="Apologize, say you could not complete the lookup, and offer to retry "
                "once or hand off to staff. Do not guess.",
            )
        if r.code in ("authorization_expired", "authentication_required"):
            self._auth = None
            self.tracker.set_conversation(Conversation.WAITING_VERIFICATION)
        return ToolResult(
            ok=False,
            status="rejected",
            code=r.code,
            message=r.message,
            guidance=REJECTION_GUIDANCE.get(r.code, "Explain this plainly and offer next steps."),
        )

    # ---------------------------------------------------------------- read tools --------------
    async def get_clinic_information(self, a: ClinicInfoArgs) -> ToolResult:
        from voice_agent.instructions import describe_hours, describe_policy, describe_types

        d = self.ctx.config.details
        parts: dict[str, Any] = {}
        if a.topic in ("hours", "all"):
            parts["hours"] = describe_hours(self.ctx)
        if a.topic in ("services", "all"):
            parts["services"] = describe_types(self.ctx)
        if a.topic in ("policies", "all"):
            parts["policies"] = describe_policy(self.ctx)
        if a.topic in ("location", "all"):
            parts["location"] = d.location
        if a.topic in ("contact", "all"):
            parts["contact"] = {"phone": d.phone, "email": d.email}
        self.used_information_tools = True
        return ToolResult(
            ok=True,
            status="ok",
            data={"clinic": d.name, **parts},
            message="From the clinic's published configuration.",
        )

    async def get_appointment_availability(self, a: AvailabilityArgs) -> ToolResult:
        t = self._resolve_type(a.appointment_type)
        if isinstance(t, ToolResult):
            return t
        if t.requires_human_escalation:
            return _escalation_required(t)
        if a.date_to and a.date_to < a.date_from:
            return _err("invalid_arguments", "date_to is before date_from.")
        r = await self.client.availability(
            t.id,
            a.date_from.isoformat(),
            a.date_to.isoformat() if a.date_to else None,
            a.max_results,
        )
        if not r.ok:
            return self._api_failure(r)
        body = r.body
        slots = body["slots"][: a.max_results]
        out = []
        for s in slots:
            ref = f"S{len(self.slots) + 1}"
            self.slots[ref] = {
                "start_at": s["start_at"],
                "start_local": s["start_local"],
                "type_id": str(t.id),
                "type_name": t.name,
            }
            out.append({"slot_ref": ref, "when": speak_time(s["start_local"])})
        self.used_information_tools = True
        if (
            self.tracker.operation
            in (
                Operation.NONE,
                Operation.VERIFIED,
                Operation.AVAILABILITY_SHOWN,
            )
            and self.tracker.operation != Operation.VERIFIED
        ):
            self.tracker.set_operation(Operation.AVAILABILITY_SHOWN)
        return ToolResult(
            ok=True,
            status="ok",
            message=f"{len(out)} open time(s) for {t.name} ({t.duration_minutes} min), "
            f"clinic time zone {body['timezone']}."
            if out
            else f"No open times for {t.name} in that range.",
            data={"appointment_type": t.name, "slots": out, "more_available": body["truncated"]},
            guidance="Offer these times to the caller."
            if out
            else "Offer to search a different date range.",
        )

    async def verify_patient(self, a: VerifyArgs) -> ToolResult:
        found = await self.client.find_patients(a.patient_name)
        if not found.ok:
            return self._api_failure(found)
        matches = found.body
        if not matches:
            return self._verification_failed()
        if len(matches) > 1:
            return ToolResult(
                ok=False,
                status="needs_input",
                code="ambiguous_patient",
                message="More than one patient matches that name.",
                guidance="Ask the caller for their full legal name.",
            )
        pid = uuid.UUID(matches[0]["id"])
        r = await self.client.verify(pid, a.date_of_birth.isoformat(), a.phone_last4)
        if r.ok:
            self._auth = r.body["authorization_token"]
            self.patient_id, self.patient_name = pid, matches[0]["full_name"]
            self._verify_failures = 0
            if self.tracker.operation in (Operation.NONE, Operation.AVAILABILITY_SHOWN):
                self.tracker.set_operation(Operation.VERIFIED)
            self.tracker.set_conversation(Conversation.THINKING)
            return ToolResult(
                ok=True,
                status="ok",
                message="Caller verified (simulated verification).",
                data={"patient_name": self.patient_name},
            )
        if r.code == "verification_locked":
            return ToolResult(
                ok=False,
                status="rejected",
                code="verification_locked",
                message="Verification is temporarily locked after too many attempts.",
                guidance="Do not try again. Offer a human hand-off.",
            )
        if r.kind == "rejected" and r.code == "verification_failed":
            return self._verification_failed()
        return self._api_failure(r)

    def _verification_failed(self) -> ToolResult:
        self._verify_failures += 1
        self.tracker.set_conversation(Conversation.WAITING_VERIFICATION)
        again = self._verify_failures < 3
        return ToolResult(
            ok=False,
            status="rejected",
            code="verification_failed",
            message="The details did not match our records.",
            guidance=(
                "Say you couldn't verify and offer one more try, without saying which "
                "detail was wrong."
                if again
                else "Stop retrying and offer a human hand-off."
            ),
        )

    async def get_patient_appointments(self, _: NoArgs) -> ToolResult:
        assert self.patient_id and self._auth
        r = await self.client.appointments(self.patient_id, self._auth)
        if not r.ok:
            return self._api_failure(r)
        self.appts.clear()
        out = []
        for ap in r.body:
            if ap["status"] != "scheduled":
                continue
            ref = f"A{len(self.appts) + 1}"
            self.appts[ref] = ap
            out.append(
                {
                    "appointment_ref": ref,
                    "type": ap["type_name"],
                    "when": speak_time(ap["start_local"]),
                }
            )
        self.used_information_tools = True
        return ToolResult(
            ok=True,
            status="ok",
            data={"appointments": out},
            message=f"{len(out)} upcoming appointment(s)."
            if out
            else "No upcoming appointments on file.",
        )

    # ---------------------------------------------------------------- propose tools -----------
    async def _create_proposal(
        self,
        action: str,
        body: dict[str, Any],
        *,
        type_id: uuid.UUID | None,
        appointment_id: str | None,
        start_at: str | None,
        reason: str | None,
    ) -> ToolResult:
        assert self._auth
        await self._invalidate_pending("superseded")
        r = await self.client.propose(self._auth, {"action": action, **body})
        if not r.ok:
            return self._api_failure(r)
        p = r.body
        sid = str(self.ctx.call_session_id)[:8]
        self.pending = Pending(
            proposal_id=uuid.UUID(p["id"]),
            confirmation_token=p["confirmation_token"],
            action=action,  # type: ignore[arg-type]
            summary=p["summary"],
            key=f"voice-{sid}-{p['id']}",
            start_at=start_at,
            appointment_type_id=type_id,
            appointment_id=appointment_id,
            reason=reason,
            turns_at_proposal=len(self.user_turns),
        )
        self.tracker.set_operation(Operation.PROPOSED)
        self.tracker.set_conversation(Conversation.AWAITING_CONFIRMATION)
        return ToolResult(
            ok=True,
            status="ok",
            code="awaiting_caller_confirmation",
            message=p["summary"],
            data={"proposal_summary": p["summary"], "expires_at": p["expires_at"]},
            guidance="Read this back to the caller (type, date, time and any change) and ask "
            "for an explicit yes. Do not call confirm_operation until they answer.",
        )

    async def propose_booking(self, a: ProposeBookArgs) -> ToolResult:
        t = self._resolve_type(a.appointment_type)
        if isinstance(t, ToolResult):
            return t
        if t.requires_human_escalation:
            return _escalation_required(t)
        slot = self.slots.get(a.slot_ref)
        if slot is None:
            return _err("unknown_slot_ref", "That slot was not offered. Check availability first.")
        if slot["type_id"] != str(t.id):
            return _err("slot_type_mismatch", "That slot is for a different appointment type.")
        return await self._create_proposal(
            "book",
            {"appointment_type_id": str(t.id), "start_at": slot["start_at"]},
            type_id=t.id,
            appointment_id=None,
            start_at=slot["start_at"],
            reason=None,
        )

    async def propose_reschedule(self, a: ProposeRescheduleArgs) -> ToolResult:
        ap = self.appts.get(a.appointment_ref)
        slot = self.slots.get(a.slot_ref)
        if ap is None:
            return _err("unknown_appointment_ref", "Look up the caller's appointments first.")
        if slot is None:
            return _err("unknown_slot_ref", "That slot was not offered. Check availability first.")
        if slot["type_id"] != ap["appointment_type_id"]:
            return _err("slot_type_mismatch", "That slot is for a different appointment type.")
        return await self._create_proposal(
            "reschedule",
            {"appointment_id": ap["id"], "start_at": slot["start_at"]},
            type_id=None,
            appointment_id=ap["id"],
            start_at=slot["start_at"],
            reason=None,
        )

    async def propose_cancellation(self, a: ProposeCancelArgs) -> ToolResult:
        ap = self.appts.get(a.appointment_ref)
        if ap is None:
            return _err("unknown_appointment_ref", "Look up the caller's appointments first.")
        body: dict[str, Any] = {"appointment_id": ap["id"]}
        if a.reason:
            body["reason"] = a.reason
        return await self._create_proposal(
            "cancel", body, type_id=None, appointment_id=ap["id"], start_at=None, reason=a.reason
        )

    async def _invalidate_pending(self, why: str) -> None:
        p = self.pending
        if p is None:
            return
        self.pending = None
        if self._auth and not p.confirmed:
            await self.client.reject_proposal(self._auth, p.proposal_id)  # best effort
        if self.tracker.operation in (Operation.PROPOSED, Operation.CONFIRMED):
            self.tracker.set_operation(Operation.INVALIDATED)
        self.rec.record(
            "operation",
            {"event": "proposal_invalidated", "why": why, "proposal_id": str(p.proposal_id)},
        )

    async def withdraw_pending_proposal(self, a: WithdrawArgs) -> ToolResult:
        if self.pending is None:
            return ToolResult(ok=True, status="ok", message="Nothing was pending.")
        await self._invalidate_pending(a.reason or "caller_withdrew")
        self.tracker.set_conversation(Conversation.LISTENING)
        return ToolResult(
            ok=True, status="ok", message="The pending change was withdrawn; nothing was changed."
        )

    # ---------------------------------------------------------------- confirm / execute -------
    async def confirm_operation(self, a: ConfirmArgs) -> ToolResult:
        p = self.pending
        if p is None or not self._auth:
            return _err(
                "nothing_to_confirm",
                "There is no pending change to confirm.",
                guidance="Propose the change first.",
            )
        fresh = self.user_turns[p.turns_at_proposal :]
        if not fresh:
            return ToolResult(
                ok=False,
                status="needs_input",
                code="confirmation_not_heard",
                message="The caller has not responded since the proposal.",
                guidance="Read the proposal back and wait for the caller's answer.",
            )
        said = _norm(a.caller_words)
        if not said or not any(said in _norm(t) for t in fresh):
            return ToolResult(
                ok=False,
                status="needs_input",
                code="confirmation_not_heard",
                message="Those words were not what the caller said after the proposal.",
                guidance="Quote the caller's actual answer, or ask them again.",
            )
        if not p.confirmed:
            c = await self.client.confirm_proposal(self._auth, p.proposal_id, p.confirmation_token)
            if not c.ok:
                if c.kind == "unavailable":
                    return self._api_failure(c)  # proposal still pending; safe to retry
                self.pending = None
                self.tracker.set_operation(Operation.INVALIDATED)
                self.tracker.set_conversation(Conversation.LISTENING)
                return self._api_failure(c)
            p.confirmed = True
            self.tracker.set_operation(Operation.CONFIRMED)
        self.tracker.set_conversation(Conversation.EXECUTING_TOOL)
        self.tracker.set_operation(Operation.EXECUTING)
        self.rec.record("operation", {"event": "executing", "action": p.action, "key": p.key})
        return await self._execute(p, first=True)

    def _exec_body(self, p: Pending) -> dict[str, Any]:
        if p.action == "book":
            return {
                "proposal_id": str(p.proposal_id),
                "appointment_type_id": str(p.appointment_type_id),
                "start_at": p.start_at,
            }
        if p.action == "reschedule":
            return {"proposal_id": str(p.proposal_id), "new_start_at": p.start_at}
        body: dict[str, Any] = {"proposal_id": str(p.proposal_id)}
        if p.reason:
            body["reason"] = p.reason
        return body

    async def _execute(self, p: Pending, *, first: bool) -> ToolResult:
        assert self._auth
        r = await self.client.execute(
            self._auth, p.key, p.action, self._exec_body(p), p.appointment_id
        )
        if r.operation_id:
            p.operation_id = r.operation_id
        if r.ok:
            return self._committed(p, r.body["appointment"], r.operation_id, r.replay)
        if r.kind == "rejected":
            return self._rejected(p, r)
        self.tracker.set_operation(
            Operation.UNKNOWN
        ) if self.tracker.operation != Operation.UNKNOWN else None
        self.last_unknown = p
        return await self._reconcile(p, retry_same_key=first)

    async def _reconcile(self, p: Pending, *, retry_same_key: bool) -> ToolResult:
        """Find out what really happened, using the idempotency key we already hold."""
        assert self._auth
        self.tracker.set_conversation(Conversation.RECOVERING)
        retried = False
        for attempt in range(self._attempts):
            r = await self.client.operation_by_key(self._auth, p.key)
            self.rec.record(
                "operation",
                {
                    "event": "reconcile",
                    "attempt": attempt + 1,
                    "key": p.key,
                    "result": r.kind,
                    "code": r.code,
                },
            )
            if r.ok:
                op = r.body
                p.operation_id = op["id"]
                if op["status"] == "succeeded":
                    appt = (op.get("outcome") or {}).get("appointment") or {}
                    return self._committed(p, appt, op["id"], True)
                if op["status"] == "failed":
                    err = (op.get("outcome") or {}).get("error") or {}
                    return self._rejected(
                        p,
                        ApiResult(
                            "rejected",
                            op.get("http_status"),
                            code=str(err.get("code", "operation_failed")),
                            message=str(err.get("message", "The operation failed.")),
                            operation_id=op["id"],
                        ),
                    )
                if op["status"] == "aborted" and retry_same_key and not retried:
                    retried = True
                    again = await self.client.execute(
                        self._auth, p.key, p.action, self._exec_body(p), p.appointment_id
                    )
                    if again.ok:
                        return self._committed(
                            p, again.body["appointment"], again.operation_id, again.replay
                        )
                    if again.kind == "rejected":
                        return self._rejected(p, again)
            elif r.code == "not_found" and retry_same_key and not retried:
                # The backend has no record: the request never landed. Retrying with the SAME key
                # is safe; a new key could double-book.
                retried = True
                again = await self.client.execute(
                    self._auth, p.key, p.action, self._exec_body(p), p.appointment_id
                )
                if again.ok:
                    return self._committed(
                        p, again.body["appointment"], again.operation_id, again.replay
                    )
                if again.kind == "rejected":
                    return self._rejected(p, again)
            await self._sleep(min(0.25 * (attempt + 1), 1.0))
        self.metrics.uncertain += 1
        if self.tracker.operation != Operation.UNKNOWN:
            self.tracker.set_operation(Operation.UNKNOWN)
        self.last_unknown = p
        return ToolResult(
            ok=False,
            status="uncertain",
            code="outcome_unknown",
            operation_id=p.operation_id,
            message="I could not confirm whether the change went through.",
            data={"operation_key": p.key},
            guidance="Tell the caller you are not certain yet. Call get_operation_status to "
            "check. Never say it succeeded or failed until it reports a final status, and never "
            "propose the same change again.",
        )

    def _committed(
        self, p: Pending, appt: dict[str, Any], op_id: str | None, replay: bool
    ) -> ToolResult:
        self.pending = None
        self.last_unknown = None
        self.metrics.committed += 1
        record = {"action": p.action, "appointment_id": appt.get("id"), "operation_id": op_id}
        self.committed.append(record)
        self.tracker.set_operation(Operation.COMMITTED)
        self.tracker.set_conversation(Conversation.THINKING)
        self.rec.record("operation", {"event": "committed", **record, "replayed": replay})
        when = speak_time(appt["start_local"]) if appt.get("start_local") else ""
        verb = {"book": "booked", "reschedule": "rescheduled", "cancel": "cancelled"}[p.action]
        return ToolResult(
            ok=True,
            status="committed",
            operation_id=op_id,
            message=f"The appointment is {verb}."
            + (f" It is now {when}." if p.action != "cancel" and when else ""),
            data={
                "action": p.action,
                "type": appt.get("type_name"),
                "when": when,
                "status": appt.get("status"),
            },
            guidance="Tell the caller the result and ask if they need anything else.",
        )

    def _rejected(self, p: Pending, r: ApiResult) -> ToolResult:
        self.pending = None
        self.last_unknown = None
        self.metrics.rejected += 1
        self.tracker.set_operation(Operation.REJECTED)
        self.tracker.set_conversation(Conversation.THINKING)
        self.rec.record(
            "operation",
            {
                "event": "rejected",
                "action": p.action,
                "code": r.code,
                "operation_id": r.operation_id,
            },
        )
        return ToolResult(
            ok=False,
            status="rejected",
            code=r.code,
            message=r.message,
            operation_id=r.operation_id,
            guidance=REJECTION_GUIDANCE.get(r.code, "Explain this plainly; nothing was changed."),
        )

    async def get_operation_status(self, _: NoArgs) -> ToolResult:
        p = self.last_unknown
        if p is None or not self._auth:
            if self.committed:
                last = self.committed[-1]
                return ToolResult(
                    ok=True,
                    status="committed",
                    operation_id=last["operation_id"],
                    message=f"The last change ({last['action']}) was committed.",
                )
            return _err("no_operation", "There is no operation to check.")
        return await self._reconcile(p, retry_same_key=True)

    # ---------------------------------------------------------------- escalation --------------
    async def request_human_escalation(self, a: EscalateArgs) -> ToolResult:
        await self._invalidate_pending("escalated")
        self.escalation_reason = a.reason
        self.tracker.set_conversation(Conversation.ESCALATED)
        self.rec.record("system", {"event": "escalation_requested", "reason": a.reason})
        return ToolResult(
            ok=True,
            status="ok",
            code="escalation_recorded",
            message="A hand-off request was recorded for clinic staff. No live transfer happens "
            "in this environment.",
            data={
                "instructions": self.ctx.config.agent.escalation_instructions,
                "transfer_performed": False,
            },
            guidance="Tell the caller staff will follow up, using the escalation instructions. "
            "Do not claim the call was transferred.",
        )


def _err(code: str, message: str, guidance: str = "") -> ToolResult:
    return ToolResult(ok=False, status="error", code=code, message=message, guidance=guidance)


def _invalid(e: ValidationError) -> ToolResult:
    fields = "; ".join(
        f"{'.'.join(str(x) for x in er['loc']) or 'arguments'}: {er['msg']}" for er in e.errors()
    )
    return ToolResult(
        ok=False,
        status="needs_input",
        code="invalid_arguments",
        message=f"Invalid arguments ({fields}).",
        guidance="Ask the caller for the missing or unclear detail.",
    )


def _escalation_required(t: AppointmentTypeInfo) -> ToolResult:
    return ToolResult(
        ok=False,
        status="rejected",
        code="human_escalation_required",
        message=f"{t.name} cannot be booked by the voice agent.",
        guidance="Explain that staff handle this, and use request_human_escalation.",
    )


_SPECS: dict[str, tuple[type[BaseModel], str]] = {
    "get_clinic_information": (ClinicInfoArgs, "get_clinic_information"),
    "get_appointment_availability": (AvailabilityArgs, "get_appointment_availability"),
    "verify_patient": (VerifyArgs, "verify_patient"),
    "get_patient_appointments": (NoArgs, "get_patient_appointments"),
    "propose_booking": (ProposeBookArgs, "propose_booking"),
    "propose_reschedule": (ProposeRescheduleArgs, "propose_reschedule"),
    "propose_cancellation": (ProposeCancelArgs, "propose_cancellation"),
    "confirm_operation": (ConfirmArgs, "confirm_operation"),
    "get_operation_status": (NoArgs, "get_operation_status"),
    "withdraw_pending_proposal": (WithdrawArgs, "withdraw_pending_proposal"),
    "request_human_escalation": (EscalateArgs, "request_human_escalation"),
}
