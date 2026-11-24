"""Utilities plugin entry point: importing the sibling modules registers their cards and actions."""

from counter_card import CounterCard, decrement, increment, reset
from display_brightness import BrightnessLevelCard, brightness, monitor_options
from navigation import PageCard, ProfileCard, page, profile

__all__ = [
    "BrightnessLevelCard",
    "CounterCard",
    "PageCard",
    "ProfileCard",
    "brightness",
    "decrement",
    "increment",
    "monitor_options",
    "page",
    "profile",
    "reset",
]
