"""The Harness itself: what later tasks can rely on when they drive their own cards through it."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from assertpy import assert_that
from decker_plugin_sdk import ActionCallContext, CardContext, DeckerPlugin, _actions, action

sys.path.insert(0, str(Path(__file__).parent))
from _harness import Harness, load_plugin  # noqa: E402

_CARD = "com.decker.utilities.counter"
_INC = "com.decker.utilities.counter-increment"


@pytest.fixture(name="harness")
def harness_fixture():
    harness = Harness(load_plugin(), _CARD, "CounterCard")
    yield harness
    harness.close()


def test_hello_is_answered_with_ready_and_a_card_paints_on_appear(harness):
    harness.appear({"max": 0})

    assert_that(harness.recv_until("set_image")["event"]).is_equal_to("set_image")


def test_run_action_returns_the_result(harness):
    harness.appear({"max": 0})
    harness.recv_until("set_image")

    result = harness.run_action(_INC, {"step": 2})

    assert_that(result["ok"]).is_true()


def test_sent_payloads_filters_by_event_and_drops_the_request_id(harness):
    harness.sent = [
        {"event": "set_title", "payload": {"request": "r1", "title": "a"}},
        {"event": "log", "payload": {"message": "m"}},
        {"event": "set_title", "payload": {"title": "b"}},
    ]

    assert_that(harness.sent_payloads("set_title")).is_equal_to([{"title": "a"}, {"title": "b"}])


def test_messages_sent_before_a_result_are_still_delivered_to_recv(harness):
    harness.appear({"max": 0})
    harness.recv_until("set_image")
    harness.run_action(_INC, {"step": 1})
    before_result = [m["event"] for m in harness.sent]

    delivered = [harness.recv()["event"] for _ in before_result]

    assert_that(delivered).is_equal_to(before_result)


def test_run_action_without_a_card_reports_the_error(harness):
    result = harness.run_action(_INC, {"step": 1}, with_card=False)

    assert_that(result["ok"]).is_false()


def test_card_settings_changes_reach_later_actions(harness):
    harness.appear({"max": 0})
    blank = harness.recv_until("set_image")["payload"]["image"]
    harness.change({"max": 1})
    harness.recv_until("set_image")

    harness.run_action(_INC, {"step": 1})  # reaches the max set by change(): wraps back to 0

    assert_that(harness.recv_until("set_image")["payload"]["image"]).is_equal_to(blank)


def test_send_event_without_a_context_reaches_the_plugin(harness):
    harness.send_event("ping")

    assert_that(harness.recv_until("pong")["event"]).is_equal_to("pong")


class _ProbeCard(DeckerPlugin):
    """Records the device the server says it is on."""

    devices: list[str] = []

    def on_will_appear(self, ctx: CardContext) -> None:
        self.devices.append(ctx.device)
        ctx.set_title("seen")


@pytest.fixture(name="probe")
def probe_fixture(monkeypatch):
    """A harness whose plugin has one extra action that reports the device of its call, card and context."""
    monkeypatch.setattr(_actions, "_ACTIONS", dict(_actions._ACTIONS))
    calls: list[tuple[str | None, str | None]] = []

    @action("com.decker.utilities.zz-probe")
    def probe(ctx: ActionCallContext) -> None:
        calls.append((ctx.device_id, ctx.card.device if ctx.card else None))
        ctx.switch_page("next")

    _ProbeCard.devices = []
    harness = Harness(SimpleNamespace(Probe=_ProbeCard), "com.decker.utilities.zz-probe", "Probe")
    harness.calls = calls
    yield harness
    harness.close()


_PROBE = "com.decker.utilities.zz-probe"


def test_appear_and_run_action_default_to_the_same_device(probe):
    probe.appear({})
    probe.recv_until("set_title")

    probe.run_action(_PROBE, {})

    assert_that(probe.calls).is_equal_to([(_ProbeCard.devices[0], _ProbeCard.devices[0])])


def test_a_context_less_run_action_carries_the_chosen_device(probe):
    probe.run_action(_PROBE, {}, with_card=False, device="other")

    assert_that(probe.calls).is_equal_to([("other", None)])
    assert_that(probe.sent_payloads("switch_page")).is_equal_to([{"device": "other", "to": "next", "wrap": False}])


def test_sent_payloads_only_reflects_the_current_action(probe):
    probe.run_action(_PROBE, {}, with_card=False, device="first")

    probe.run_action(_PROBE, {}, with_card=False, device="second")

    assert_that(probe.sent_payloads("switch_page")).is_length(1)
    assert_that(probe.sent_payloads("switch_page")[0]["device"]).is_equal_to("second")


def test_close_fails_when_the_plugin_thread_does_not_stop(monkeypatch):
    harness = Harness(load_plugin(), _CARD, "CounterCard")
    monkeypatch.setattr(harness, "send_event", lambda *args, **kwargs: None)  # the shutdown never arrives
    monkeypatch.setattr(harness._thread, "join", lambda timeout=None: None)

    with pytest.raises(AssertionError, match="did not stop"):
        harness.close()

    monkeypatch.undo()
    harness.close()


# --- the deck brightness side of the server ---


@pytest.fixture(name="deck")
def deck_fixture():
    """A harness whose plugin has one extra action that reads and sets the deck brightness."""
    from decker_plugin_sdk import get_deck_brightness, set_deck_brightness

    saved = dict(_actions._ACTIONS)

    @action("com.decker.utilities.zz-deck")
    def deck_probe(ctx: ActionCallContext) -> int:
        level = get_deck_brightness(ctx.args.get("device"))
        set_deck_brightness(level + 1, ctx.args.get("device"))
        return level

    harness = Harness(SimpleNamespace(Probe=_ProbeCard), "com.decker.utilities.zz-probe", "Probe")
    yield harness
    harness.close()
    _actions._ACTIONS.clear()
    _actions._ACTIONS.update(saved)


def test_the_harness_answers_get_deck_brightness_from_deck_levels(deck):
    deck.deck_levels["dev9"] = 33

    result = deck.run_action("com.decker.utilities.zz-deck", {"device": "dev9"}, with_card=False)

    assert_that(result["value"]).is_equal_to(33)
    assert_that(deck.deck_gets).is_equal_to(["dev9"])


def test_the_harness_records_set_deck_brightness_payloads(deck):
    deck.run_action("com.decker.utilities.zz-deck", {}, with_card=False)

    assert_that(deck.deck_sets).is_equal_to([{"device": "dev1", "percent": 51}])


def test_an_unknown_deck_gets_an_error_reply(deck):
    result = deck.run_action("com.decker.utilities.zz-deck", {"device": "nope"}, with_card=False)

    assert_that(result["ok"]).is_false()
    assert_that(result["error"]).contains("unknown device")
    assert_that(deck.deck_sets).is_empty()


def test_deck_events_helpers_reach_the_plugin(deck):
    from decker_plugin_sdk import connected_devices

    deck.connect("dev7")
    deck.run_action("com.decker.utilities.zz-deck", {}, with_card=False)  # barrier: the reader has seen the event
    assert_that(connected_devices()).contains("dev7")

    deck.disconnect("dev7")
    deck.run_action("com.decker.utilities.zz-deck", {}, with_card=False)
    assert_that(connected_devices()).does_not_contain("dev7")
