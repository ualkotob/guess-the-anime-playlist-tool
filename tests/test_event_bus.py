"""Tests for core/event_bus.py."""

from core.event_bus import EventBus


def test_publish_calls_subscribers_in_order():
    bus = EventBus()
    calls = []
    bus.subscribe("evt", lambda p: calls.append(("first", p)))
    bus.subscribe("evt", lambda p: calls.append(("second", p)))
    bus.publish("evt", {"x": 1})
    assert calls == [("first", {"x": 1}), ("second", {"x": 1})]


def test_publish_with_no_subscribers_is_noop():
    EventBus().publish("nobody-listening")


def test_default_payload_is_none():
    bus = EventBus()
    seen = []
    bus.subscribe("evt", seen.append)
    bus.publish("evt")
    assert seen == [None]


def test_unsubscribe():
    bus = EventBus()
    seen = []
    cb = seen.append
    bus.subscribe("evt", cb)
    bus.unsubscribe("evt", cb)
    bus.publish("evt", 1)
    assert seen == []


def test_unsubscribe_unknown_is_noop():
    bus = EventBus()
    bus.unsubscribe("evt", lambda p: None)  # never subscribed — must not raise


def test_failing_subscriber_does_not_block_others(capsys):
    bus = EventBus()
    seen = []

    def boom(payload):
        raise RuntimeError("subscriber bug")

    bus.subscribe("evt", boom)
    bus.subscribe("evt", seen.append)
    bus.publish("evt", 42)
    assert seen == [42]
    assert "subscriber bug" in capsys.readouterr().err


def test_subscriber_modifying_list_during_publish_is_safe():
    bus = EventBus()
    seen = []

    def unsubscribing(payload):
        bus.unsubscribe("evt", unsubscribing)
        seen.append("un")

    bus.subscribe("evt", unsubscribing)
    bus.subscribe("evt", lambda p: seen.append("after"))
    bus.publish("evt")
    assert seen == ["un", "after"]
    # Second publish: only the remaining subscriber fires.
    bus.publish("evt")
    assert seen == ["un", "after", "after"]
