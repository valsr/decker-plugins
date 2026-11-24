"""The Harness itself: what later tasks can rely on when they drive their own cards through it."""

import sys
from pathlib import Path

import pytest
from assertpy import assert_that

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
