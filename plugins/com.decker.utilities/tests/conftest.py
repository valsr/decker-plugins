"""Keep every test off the real hardware: the brightness service starts with an empty backend."""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from brightness import Monitor  # noqa: E402
from deck_brightness import reset_for_tests  # noqa: E402
from display_brightness import set_backend_for_tests  # noqa: E402
from sleep_card import reset_for_tests as reset_sleep  # noqa: E402


class _NoMonitors:
    def list_monitors(self) -> list[Monitor]:
        return []

    def get(self, monitor_id: str) -> int:
        raise KeyError(monitor_id)

    def set(self, monitor_id: str, percent: int) -> None:
        raise KeyError(monitor_id)


def hardware_free() -> Iterator[None]:
    """Setup and teardown of the autouse fixture; the teardown keeps the empty backend, never the real default."""
    set_backend_for_tests(_NoMonitors())
    reset_for_tests()
    reset_sleep()
    yield
    set_backend_for_tests(_NoMonitors())


@pytest.fixture(autouse=True)
def _no_hardware() -> Iterator[None]:
    yield from hardware_free()
