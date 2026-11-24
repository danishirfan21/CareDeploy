"""Domain errors. Each carries a stable machine-readable `code` and an HTTP status.

None of these ever include stack traces or database details.
"""

from typing import Any


class SchedulingError(Exception):
    status_code = 400
    code = "scheduling_error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.headers = headers or {}

    def body(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            err["details"] = self.details
        return {"error": err}


class InvalidInput(SchedulingError):
    status_code = 422
    code = "invalid_input"


class AuthenticationRequired(SchedulingError):
    status_code = 401
    code = "authentication_required"


class AuthorizationExpired(SchedulingError):
    status_code = 401
    code = "authorization_expired"


class Forbidden(SchedulingError):
    status_code = 403
    code = "forbidden"


class VerificationFailed(SchedulingError):
    status_code = 403
    code = "verification_failed"


class VerificationLocked(SchedulingError):
    status_code = 429
    code = "verification_locked"


class NotFound(SchedulingError):
    status_code = 404
    code = "not_found"


class ClinicNotConfigured(SchedulingError):
    """No usable published configuration: scheduling only reads published versions."""

    status_code = 409
    code = "clinic_not_configured"


class PolicyViolation(SchedulingError):
    """A clinic rule rejected the request. `details.rule` names the rule."""

    status_code = 422
    code = "policy_violation"

    def __init__(self, rule: str, message: str, **details: Any) -> None:
        super().__init__(message, details={"rule": rule, **details})
        self.rule = rule


class SlotUnavailable(SchedulingError):
    status_code = 409
    code = "slot_unavailable"


class InvalidStateTransition(SchedulingError):
    status_code = 409
    code = "invalid_state_transition"


class AppointmentModified(SchedulingError):
    status_code = 409
    code = "appointment_modified"


class IdempotencyConflict(SchedulingError):
    status_code = 409
    code = "idempotency_conflict"


class OperationInProgress(SchedulingError):
    status_code = 409
    code = "operation_in_progress"


class ProposalExpired(SchedulingError):
    status_code = 410
    code = "operation_expired"


class ProposalMismatch(SchedulingError):
    status_code = 409
    code = "proposal_mismatch"


class ProposalNotConfirmed(SchedulingError):
    status_code = 409
    code = "proposal_not_confirmed"


class ProposalAlreadyUsed(SchedulingError):
    status_code = 409
    code = "proposal_already_used"


class DependencyUnavailable(SchedulingError):
    """Temporary failure; the outcome of the operation is known not to have been committed."""

    status_code = 503
    code = "dependency_unavailable"


class OutcomeUnknown(SchedulingError):
    """The response was lost or the commit could not be confirmed. Reconcile before retrying."""

    status_code = 503
    code = "outcome_unknown"
