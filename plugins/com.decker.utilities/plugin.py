"""Utilities plugin entry point: importing the sibling modules registers their cards and actions."""

from counter_card import CounterCard, decrement, increment, reset
from deck_brightness import DeckBrightnessLevelCard, deck_brightness
from display_brightness import BrightnessLevelCard, brightness, monitor_options
from navigation import PageCard, ProfileCard, page, profile
from sleep_card import SleepCard, lock, sleep, sleep_after, sleep_cancel, sleep_press
from stopwatch_card import StopwatchCard, stopwatch_reset, stopwatch_toggle
from timer_card import TimerCard, timer_reset, timer_toggle

__all__ = [
    "BrightnessLevelCard",
    "CounterCard",
    "DeckBrightnessLevelCard",
    "PageCard",
    "ProfileCard",
    "SleepCard",
    "StopwatchCard",
    "TimerCard",
    "brightness",
    "deck_brightness",
    "decrement",
    "increment",
    "lock",
    "monitor_options",
    "page",
    "profile",
    "reset",
    "sleep",
    "sleep_after",
    "sleep_cancel",
    "sleep_press",
    "stopwatch_reset",
    "stopwatch_toggle",
    "timer_reset",
    "timer_toggle",
]
