import pytest

from voice_agent.states import (
    Conversation,
    InvalidTransition,
    Operation,
    StateTracker,
    Transport,
)


def test_transport_happy_path_and_illegal_edges() -> None:
    t = StateTracker()
    assert t.transport == Transport.CONNECTING
    assert t.set_transport(Transport.CONNECTED)
    assert t.set_transport(Transport.RECONNECTING)
    assert t.set_transport(Transport.CONNECTED)
    t.set_transport(Transport.DISCONNECTED)
    with pytest.raises(InvalidTransition):
        t.set_transport(Transport.CONNECTED)


def test_conversation_cannot_speak_before_connecting() -> None:
    t = StateTracker()
    with pytest.raises(InvalidTransition):
        t.set_conversation(Conversation.SPEAKING)
    t.set_transport(Transport.CONNECTED)
    t.set_conversation(Conversation.READY)
    t.set_conversation(Conversation.LISTENING)
    t.set_conversation(Conversation.THINKING)
    t.set_conversation(Conversation.SPEAKING)


def test_operation_machine() -> None:
    t = StateTracker()
    with pytest.raises(InvalidTransition):
        t.set_operation(Operation.COMMITTED)
    t.set_operation(Operation.PROPOSED)
    with pytest.raises(InvalidTransition):
        t.set_operation(Operation.EXECUTING)
    t.set_operation(Operation.CONFIRMED)
    t.set_operation(Operation.EXECUTING)
    t.set_operation(Operation.UNKNOWN)
    t.set_operation(Operation.COMMITTED)
