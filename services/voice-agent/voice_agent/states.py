"""Explicit state model. Three machines that never share a variable:

* transport   - the LiveKit connection (is audio plumbing alive?)
* conversation - what the agent is doing in the dialogue (what should the caller see?)
* operation   - the scheduling operation being proposed/executed (what is true in the backend?)

Stopping audio (barge-in, disconnect) moves transport/conversation state only. It never moves the
operation machine: a backend commit that is already executing keeps executing and is reported.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class Transport(StrEnum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


class Conversation(StrEnum):
    CONNECTING = "connecting"
    READY = "ready"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    WAITING_CLARIFICATION = "waiting_for_clarification"
    WAITING_VERIFICATION = "waiting_for_verification"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING_TOOL = "executing_tool"
    RECOVERING = "recovering"
    ESCALATED = "escalated"
    COMPLETED = "completed"
    DISCONNECTED = "disconnected"


class Operation(StrEnum):
    NONE = "none"
    AVAILABILITY_SHOWN = "availability_shown"
    VERIFIED = "verified"
    PROPOSED = "proposed"  # backend proposal exists, not yet confirmed by the caller
    CONFIRMED = "confirmed"  # caller said yes; backend proposal confirmed
    EXECUTING = "executing"
    COMMITTED = "committed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"  # outcome not known; must be reconciled, never assumed
    INVALIDATED = "invalidated"  # proposal withdrawn/superseded before execution


TRANSPORT_EDGES: dict[Transport, set[Transport]] = {
    Transport.CONNECTING: {Transport.CONNECTED, Transport.FAILED, Transport.DISCONNECTED},
    Transport.CONNECTED: {Transport.RECONNECTING, Transport.DISCONNECTED, Transport.FAILED},
    Transport.RECONNECTING: {Transport.CONNECTED, Transport.DISCONNECTED, Transport.FAILED},
    Transport.DISCONNECTED: set(),
    Transport.FAILED: set(),
}

_TERMINAL_CONV = {Conversation.COMPLETED, Conversation.DISCONNECTED}
# Everything except the terminal states may move to any other state: the dialogue is driven by the
# caller, so strict ordering would only produce false errors. What is forbidden is leaving a
# terminal state, or starting a conversation before the transport exists.
CONVERSATION_EDGES: dict[Conversation, set[Conversation]] = {
    c: (set(Conversation) - {c}) if c not in _TERMINAL_CONV else set() for c in Conversation
}
CONVERSATION_EDGES[Conversation.CONNECTING] = set(Conversation) - {
    Conversation.CONNECTING,
    Conversation.SPEAKING,
    Conversation.THINKING,
    Conversation.EXECUTING_TOOL,
    Conversation.AWAITING_CONFIRMATION,
}

OPERATION_EDGES: dict[Operation, set[Operation]] = {
    Operation.NONE: {Operation.AVAILABILITY_SHOWN, Operation.VERIFIED, Operation.PROPOSED},
    Operation.AVAILABILITY_SHOWN: {
        Operation.AVAILABILITY_SHOWN,
        Operation.VERIFIED,
        Operation.PROPOSED,
        Operation.NONE,
    },
    Operation.VERIFIED: {
        Operation.AVAILABILITY_SHOWN,
        Operation.PROPOSED,
        Operation.VERIFIED,
        Operation.NONE,
    },
    Operation.PROPOSED: {Operation.CONFIRMED, Operation.INVALIDATED, Operation.PROPOSED},
    Operation.CONFIRMED: {
        Operation.EXECUTING,
        Operation.INVALIDATED,
        Operation.REJECTED,  # proposal expired/rejected by backend before execution
    },
    Operation.EXECUTING: {Operation.COMMITTED, Operation.REJECTED, Operation.UNKNOWN},
    Operation.UNKNOWN: {
        Operation.UNKNOWN,
        Operation.EXECUTING,  # same-key retry after reconciliation found no record
        Operation.COMMITTED,
        Operation.REJECTED,
    },
    # After a final outcome the caller may start a new operation.
    Operation.COMMITTED: {
        Operation.NONE,
        Operation.AVAILABILITY_SHOWN,
        Operation.VERIFIED,
        Operation.PROPOSED,
    },
    Operation.REJECTED: {
        Operation.NONE,
        Operation.AVAILABILITY_SHOWN,
        Operation.VERIFIED,
        Operation.PROPOSED,
    },
    Operation.INVALIDATED: {
        Operation.NONE,
        Operation.AVAILABILITY_SHOWN,
        Operation.VERIFIED,
        Operation.PROPOSED,
    },
}


class InvalidTransition(Exception):
    def __init__(self, machine: str, src: str, dst: str) -> None:
        super().__init__(f"{machine}: {src} -> {dst} is not allowed")
        self.machine, self.src, self.dst = machine, src, dst


@dataclass
class StateTracker:
    """Holds the three machines and notifies a listener on each accepted change."""

    on_change: Callable[[str, str, str], None] | None = None
    transport: Transport = Transport.CONNECTING
    conversation: Conversation = Conversation.CONNECTING
    operation: Operation = Operation.NONE
    history: list[tuple[str, str, str]] = field(default_factory=list)

    def _move(self, machine: str, cur: object, dst: object, edges: dict) -> bool:  # type: ignore[type-arg]
        if cur == dst:
            return False
        if dst not in edges[cur]:
            raise InvalidTransition(machine, str(cur), str(dst))
        self.history.append((machine, str(cur), str(dst)))
        if self.on_change:
            self.on_change(machine, str(cur), str(dst))
        return True

    def set_transport(self, dst: Transport) -> bool:
        changed = self._move("transport", self.transport, dst, TRANSPORT_EDGES)
        if changed:
            self.transport = dst
            if dst in (Transport.DISCONNECTED, Transport.FAILED):
                # The conversation ends with the transport; the operation machine is untouched.
                self.set_conversation(Conversation.DISCONNECTED, force=True)
        return changed

    def set_conversation(self, dst: Conversation, *, force: bool = False) -> bool:
        if self.conversation in _TERMINAL_CONV:
            if force and dst == self.conversation:
                return False
            if self.conversation == Conversation.COMPLETED and dst == Conversation.DISCONNECTED:
                self.history.append(("conversation", "completed", "disconnected"))
                self.conversation = dst
                if self.on_change:
                    self.on_change("conversation", "completed", "disconnected")
                return True
            return False  # late audio events after the call ended are ignored, not errors
        changed = self._move("conversation", self.conversation, dst, CONVERSATION_EDGES)
        if changed:
            self.conversation = dst
        return changed

    def set_operation(self, dst: Operation) -> bool:
        changed = self._move("operation", self.operation, dst, OPERATION_EDGES)
        if changed:
            self.operation = dst
        return changed

    def snapshot(self) -> dict[str, str]:
        return {
            "transport": self.transport.value,
            "conversation": self.conversation.value,
            "operation": self.operation.value,
        }
