# Utilities Plugin (`com.decker.utilities`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A first-party Utilities plugin with Sleep, Lock screen, Brightness and Deck brightness actions; Brightness/Deck Brightness Level, Sleep, Timer, Stopwatch and Counter cards; and brightness/sleep variables. The Page, Profile and Brightness/Deck Brightness Up/Down presets are not cards: their actions stay global and are reached from the Actions tab.

**Architecture:** One plugin folder. `plugin.py` holds the SDK registrations (cards, actions, variables, options) and stays thin; logic lives in sibling modules: `brightness.py` (backend interface + per-platform backends + cache/poller), `power.py` (sleep/lock per platform), `timers.py` (pure timer/stopwatch/countdown state machines), `drawing.py` (Pillow painting: tinted icons, time text, arc/bar progress, colour modes). Per-key state is held in card instances (context id) inside the long-running process (the plugin declares variables).

**Tech Stack:** Python 3.14, `decker_plugin_sdk` (Decker ≥ 0.7.2, protocol 5), Pillow ≥ 12, `screen-brightness-control` (Linux/Windows), `jeepney` (Linux), pytest + assertpy, ruff.

**Spec:** `../decker/docs/superpowers/specs/2026-11-24-utilities-plugin-design.md` (Part 2). Depends on the Decker 0.7.2 plan (`../decker/docs/superpowers/plans/2026-11-24-decker-0.7.2.md`) being merged first.

## Global Constraints

- Folder `plugins/com.decker.utilities/`, manifest `format: 3`, `id: com.decker.utilities`, `version: 1.0.0`, `"decker": ">=0.7.2"`, category `Utilities`, `homepage: https://github.com/valsr/decker-plugins`, `platforms` all three.
- `runtime.requirements`: `pillow>=12`, `screen-brightness-control; sys_platform != "darwin"`, `jeepney; sys_platform == "linux"` (use the exact requirement-marker syntax the Decker installer accepts; check `docs/plugins/package-and-manifest.md`).
- Every action/card id is `com.decker.utilities.<name>`; names as listed in each task.
- Level tint: grey = level, 100 % → `#ffffff`, 0 % → `#000000`, linear, no minimum.
- Deck brightness is clamped 1–100 by the server; plugin sends what the user computed.
- Brightness poll every 5 s; all hardware/D-Bus/subprocess calls off the message loop.
- Timers/countdowns are lost on plugin restart and never fire late.
- Sibling modules are importable because the plugin dir is on `sys.path` when Decker runs `plugin.py`; test harness inserts the plugin dir on `sys.path` too.
- The old `com.decker.counter`/`pages`/`profiles` plugins are not touched.
- Tests: `uv run pytest plugins/com.decker.utilities`; lint: `uv run ruff check plugins/com.decker.utilities`.
- README platform table updated in the same change as the code it describes (Task 9).
- Branch `feat/utilities-plugin` from `main` (after the Decker pin bump in Task 1).

## Review Focus

1. No monitors detected (desktop without ddcutil, VM) — Brightness actions fail with a clear "no monitor found" error; Level card shows `—` and the variable is empty; nothing crashes. Test in Task 4.
2. A monitor that disappears between listing and set (unplugged, DDC timeout) — that action fails with a clear error; "all" still sets the remaining monitors and reports which failed. Test in Task 4.
3. Sleep countdown running when the key's page is switched away and back — the countdown keeps going and the reappearing key shows the remaining time. Test in Task 6.
4. Timer duration changed in settings while running/paused — resets to idle with the new duration. Test in Task 7.
5. Deck brightness action with no device (called from another plugin outside any card chain) — clear ActionError, no message sent. Test in Task 5.

---

### Task 1: Scaffold, Decker pin, Counter

**Files:**
- Modify: `pyproject.toml` (pin Decker to the 0.7.2 merge commit), `uv.lock` (`uv lock`)
- Create: `plugins/com.decker.utilities/manifest.json`, `plugin.py`, `icons/utilities.svg` (any simple Font-Awesome-free SVG, e.g. a toolbox), copy `iconpack/` and `icons/counter*` from `plugins/com.decker.counter/`
- Create: `plugins/com.decker.utilities/tests/_harness.py` (generalised from `plugins/com.decker.pages/tests/_pages_harness.py`: `Harness(plugin, card_id, class_name)` with protocol 5 hello, `appear`, `change`, `run_action(action_id, args, with_card=True, device="dev1")`, `sent_payloads(event)`, `send_event(event, payload)`), `tests/test_manifest.py`, `tests/test_counter.py`

**Interfaces:**
- Produces: `load_plugin() -> ModuleType` and `Harness` (above) for all later tasks; Counter ids `com.decker.utilities.counter` (card), `.counter_increment`, `.counter_decrement`, `.counter_reset` (plugin-scoped, same settings as today's Counter: `step` int 1–9999 default 1; card `max` int 0–99999 special "∞ (no limit)").

- [ ] **Step 1: Write failing tests** — manifest loads with Decker's `parse_manifest` (version 1.0.0, decker `>=0.7.2`, every icon path exists); port `plugins/com.decker.counter/tests/test_counter.py` to the new ids. If Decker plan Task 8 found the crash in the plugin, add its regression test here (e.g. `test_unparseable_step_counts_by_the_default`).
- [ ] **Step 2: Run, expect FAIL** — `uv run pytest plugins/com.decker.utilities -v`
- [ ] **Step 3: Implement** manifest skeleton (counter card + actions + icon pack; `variables` filled in later tasks — declare `brightness_level` now so the plugin is long-running from the start) and port `CounterCard` + actions from `plugins/com.decker.counter/plugin.py`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(utilities): scaffold plugin with Counter"`

---

### Task 2: Page and Profile actions

**Files:**
- Modify: `manifest.json`, `plugin.py`
- Test: `tests/test_navigation.py`

**Interfaces:**
- Consumes: SDK `ActionCallContext.device_id`, `ctx.switch_page/go_to_page/switch_profile/go_to_profile` (Decker plan Task 3); card-context versions on `ctx.card`.
- Produces: global actions `com.decker.utilities.page` {`mode` choice `page|next|previous` default `next`; `profile` profile; `page` page with `profile_field: "profile"`; `wrap` bool default false} and `com.decker.utilities.profile` {`mode` `profile|next|previous` default `next`; `profile` profile; `wrap` bool}.  There are no Page or Profile cards (a Blank card plus the action does the same); the actions are reached from the Actions tab.

Behaviour: with a card in the call, navigate through it; else through `ctx` (device-scoped); neither → `ActionError("no device for this call")`. Mode `page` with an unset/deleted page (`profile_id == -1`) → `ActionError("the chosen page no longer exists")`.

- [ ] **Step 1: Write failing tests** — each mode sends the right message (`switch_page {"to","wrap"}` / `{"page_id"}` / `switch_profile {"profile_id"}`) through the card when present and context-less with `device` when not; deleted page error.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(utilities): Page and Profile actions"`

---

### Task 3: Brightness backends

**Files:**
- Create: `plugins/com.decker.utilities/brightness.py`
- Test: `tests/test_brightness_backends.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Monitor:
    id: str      # stable: "backlight:<sysfs name>", "ddc:<serial or edid hash>", "win:<sbc serial/index>", "mac:internal"
    name: str    # human label

class BrightnessError(Exception): ...

class Backend(Protocol):
    def list_monitors(self) -> list[Monitor]: ...
    def get(self, monitor_id: str) -> int: ...          # 0-100
    def set(self, monitor_id: str, percent: int) -> None: ...

class LogindBacklight(Backend)   # Linux internal: read /sys/class/backlight/<n>/{brightness,max_brightness}; write via
                                 # org.freedesktop.login1 /org/freedesktop/login1/session/auto Session.SetBrightness("backlight", n, raw)
class SbcBackend(Backend)        # screen_brightness_control; on Linux method="ddcutil" only; on Windows all methods
class MacInternal(Backend)       # ctypes DisplayServices GetBrightness/SetBrightness on the main display
class CompositeBackend(Backend)  # concatenates children; routes by id prefix; a child whose list fails is skipped (logged once)
def default_backend(platform: str = sys.platform) -> Backend
def label_monitors(monitors: list[Monitor]) -> list[tuple[str, str]]  # (id, label) adding " (2)" etc. when names repeat

class BrightnessCache:
    def __init__(self, backend: Backend, interval: float = 5.0, on_change: Callable[[], None] | None = None) -> None
    def start(self) -> None; def stop(self) -> None
    def monitors(self) -> list[Monitor]
    def level(self, monitor_id: str) -> int | None
    def average(self) -> int | None
    def change(self, monitor_id: str | Literal["all"], mode: Literal["increase", "decrease", "set"], value: int) -> dict[str, int]
        # returns new levels by id; clamps 0-100; for "all" applies to each, raises BrightnessError listing failures
        # only after attempting all; updates cache immediately and calls on_change
```

- [ ] **Step 1: Write failing tests** with fakes: a fake sysfs dir (tmp_path) + fake D-Bus sender for `LogindBacklight` (raw ↔ percent conversion, rounding, max 0 guarded); `SbcBackend` with a monkeypatched `screen_brightness_control` module; `CompositeBackend` routing and skipping a failing child; `label_monitors` duplicates; `BrightnessCache.change` clamping, "all" partial failure (`BrightnessError` names the failed monitor, others set), empty monitor list → `BrightnessError("no monitor found")`, poll picks up an external change and calls `on_change` only when something changed.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** D-Bus via `jeepney` (`DBusAddress`, `new_method_call`, `open_dbus_connection(bus="SYSTEM")`); imports of `jeepney`/`screen_brightness_control`/`ctypes` frameworks are lazy and platform-guarded so tests and other OSes import cleanly.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(utilities): brightness backends"`

---

### Task 4: Brightness action, cards and variables

**Files:**
- Create: `plugins/com.decker.utilities/drawing.py` (tinted icon + level text helpers)
- Modify: `manifest.json`, `plugin.py`
- Test: `tests/test_brightness.py`, `tests/test_drawing.py`

**Interfaces:**
- Consumes: Task 3 `BrightnessCache`, `default_backend`, `label_monitors`.
- Produces: `drawing.level_grey(percent: int) -> str` (`#rrggbb`), `drawing.draw_icon(img, icon_png: bytes, color: str) -> None`, `drawing.draw_caption(img, text: str) -> None`. Global action `com.decker.utilities.brightness` {`mode` choice increase/decrease/set default increase; `value` int 0–100 default 10; `monitor` choice `options_source: "monitors"` default `"all"`}, returns the new level (first changed monitor's). `@options("monitors")` → `[{"label": "All monitors", "value": "all"}, *labelled monitors]`. Card `brightness_level` (icon `fas:sun`, tinted by `monitor` card setting's level, "all" = average, caption `NN%`, `—` when unknown; bindings +10 / −10 / set 75); no Up/Down cards (the `brightness` action with `monitor: "all"` is reached from the Actions tab). Variables `brightness_level` (first monitor) and pattern `brightness_level_{monitor}` (1-based index), registered/unregistered as the monitor list changes.

- [ ] **Step 1: Write failing tests** — `level_grey(100) == "#ffffff"`, `level_grey(0) == "#000000"`, `level_grey(50) == "#808080"`; action modes and clamping through a fake backend injected via a module-level `set_backend_for_tests(backend)` hook; options list; unknown monitor id → ActionError "monitor not available"; no monitors → ActionError "no monitor found" and Level card caption `—`; Level card repaints when the cache's `on_change` fires; variable values and per-monitor registration; manifest default bindings exactly as listed.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Start the cache in `@init`, stop on shutdown; `on_change` signals variables and queues paints of live Level cards. Icons come from the bundled `fas:sun` — render via the card's icon support (`ctx.set_icon(ref, color)` from `_context.py:85`) rather than rasterising Font Awesome yourself; caption via `set_title` or drawn text (implementer's choice, consistent across Level cards).
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(utilities): display brightness action and cards"`

---

### Task 5: Deck brightness action, cards and variables

**Files:** Modify `manifest.json`, `plugin.py`. Test: `tests/test_deck_brightness.py`

**Interfaces:**
- Consumes: SDK `get_deck_brightness`, `set_deck_brightness`, `on_deck_brightness_changed`, `connected_devices`, `on_device_connected/disconnected` (Decker plan Tasks 4–5).
- Produces: global action `com.decker.utilities.deck_brightness` {`mode`, `value` as in Task 4}, device = card's `device` or `ctx.device_id`; none → `ActionError("no deck for this call")` and nothing sent; returns the computed new level. Card `deck_brightness_level` (icon `decker:logo` tinted by the key's deck level, caption `NN%`; +10 / −10 / set 75); no Up/Down cards (the `deck_brightness` action is reached from the Actions tab). Variables `deck_brightness_level` (first of `connected_devices()`) and pattern `deck_brightness_level_{device}`.

- [ ] **Step 1: Write failing tests** with the harness answering `get_deck_brightness` and asserting `set_deck_brightness` payloads: increase from 70 → sends 80; decrease from 5 by 10 → sends 0 (server clamps); set 75; no device → error, no message; `deck_brightness_changed` repaints Level cards on that device only and updates both variables; `device_disconnected` unregisters its variable and moves "first".
- [ ] **Step 2: Run, expect FAIL.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(utilities): deck brightness action and cards"`

---

### Task 6: Sleep and Lock actions, Sleep card

**Files:**
- Create: `plugins/com.decker.utilities/power.py`, `plugins/com.decker.utilities/timers.py` (countdown part)
- Modify: `manifest.json`, `plugin.py`
- Test: `tests/test_power.py`, `tests/test_sleep_card.py`

**Interfaces:**
- Produces (`power.py`): `suspend(platform: str = sys.platform) -> None`, `lock(platform: str = sys.platform) -> None`, raising `PowerError` with a readable message. Linux: system bus `org.freedesktop.login1` `/org/freedesktop/login1` `Manager.Suspend(False)`; lock: `/org/freedesktop/login1/session/auto` `Session.Lock()`. Windows: `ctypes.windll.powrprof.SetSuspendState(0, 0, 0)`, `ctypes.windll.user32.LockWorkStation()`. macOS: `pmset sleepnow`; lock: `osascript -e 'tell application "System Events" to keystroke "q" using {control down, command down}'` (non-zero exit → `PowerError` mentioning Accessibility permission). The D-Bus/ctypes/subprocess entry points are injectable for tests.
- Produces (`timers.py`): `Countdown(seconds: float, clock: Callable[[], float] = time.monotonic)` with `remaining() -> float`, `expired() -> bool`; formatting `fmt_ms(seconds: float) -> str` (`m:ss`, `h:mm:ss` from 1 h).
- Produces (plugin): global actions `com.decker.utilities.sleep` (icon `fas:moon`), `com.decker.utilities.lock` (icon `fas:lock`); plugin-scoped `com.decker.utilities.sleep_press`, `com.decker.utilities.sleep_after` {`minutes` int 1–1440 default 1}; card `com.decker.utilities.sleep` (icon `fas:moon`; bindings press → `sleep_press`, double → `sleep_after` 1, long → `sleep_after` 10). Variable `sleep_in` (soonest running countdown, `fmt_ms`, empty when none).

Behaviour: countdowns keyed by card context id in a module-level registry ticked by one background thread at 1 Hz (repaint live cards, update `sleep_in`); `sleep_press` cancels this key's countdown (`show_ok`) else suspends; `sleep_after` starts/restarts; at zero → clear, then `suspend()`; a suspend failure → log + `show_alert` on that key if live. Countdown survives `will_disappear`; on `will_appear` the key shows the remaining time.

- [ ] **Step 1: Write failing tests** — power calls per platform with injected fakes (right bus names/paths/methods; macOS osascript failure message); `sleep_press` with no countdown suspends (fake), with one cancels and does not suspend; double then press → cancelled; long during a 1-min countdown restarts at 10 min; expiry with a fake clock suspends exactly once; disappear/reappear keeps counting and shows remaining; `sleep_in` value.
- [ ] **Step 2: Run, expect FAIL.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(utilities): sleep and lock actions, Sleep card"`

---

### Task 7: Timer card

**Files:** Modify `timers.py`, `drawing.py`, `manifest.json`, `plugin.py`. Test: `tests/test_timer.py`

**Interfaces:**
- Produces (`timers.py`): `Timer(duration: float, clock=time.monotonic)` with states `idle|running|paused|finished`, `toggle()` (idle→running, running→paused, paused→running, finished→running from full), `reset()` (→ idle), `remaining() -> float`, `fraction_left() -> float`, `tick() -> bool` (True when it just finished).
- Produces (`drawing.py`): `progress_color(mode: Literal["solid","bicolor","gradient"], c1: str, c2: str, fraction_left: float) -> str` (bicolor: `c2` when `fraction_left <= 0.2`; gradient: linear `c1`→`c2` by elapsed); `draw_progress(img, kind: Literal["circle","bar"], fraction_left: float, color: str, width: int) -> None`; `draw_time(img, text: str) -> None`.
- Produces (plugin): card `com.decker.utilities.timer` (icon `fas:stopwatch`), plugin-scoped actions `timer_toggle`, `timer_reset`; bindings press → toggle, double/long → reset. Settings (exact keys/defaults): `minutes` int 0–1440 = 5, `seconds` int 0–59 = 0, `show_time` bool = true, `show_progress` bool = true, `progress_type` choice circle/bar = circle, `color_mode` choice solid/bicolor/gradient = solid, `color` color = `#2ecc71`, `color_2` color = `#e74c3c`, `line_width` int 1–20 = 6. Duration 0:00 → validation error (manifest can't express a cross-field rule: card shows `0:00` with `show_alert` on press and the action raises `ActionError("set a duration")`).

Behaviour: idle shows full duration; running repaints at 4 Hz (well under the flood limit); finishing shows `0:00` and calls `show_alert` three times 0.5 s apart; changing `minutes`/`seconds` resets to idle with the new duration; timers survive page switches like countdowns.

- [ ] **Step 1: Write failing tests** — `Timer` state machine with a fake clock (all transitions above); `progress_color` at fraction 1.0/0.5/0.2/0.0 for each mode; drawing smoke tests (pixel at arc start has `color`; bar width proportional); settings change resets; zero duration error; finish alerts.
- [ ] **Step 2: Run, expect FAIL.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(utilities): Timer card"`

---

### Task 8: Stopwatch card

**Files:** Modify `timers.py`, `manifest.json`, `plugin.py`. Test: `tests/test_stopwatch.py`

**Interfaces:**
- Produces (`timers.py`): `Stopwatch(clock=time.monotonic)` with `toggle()`, `reset()`, `elapsed() -> float`, `running: bool`.
- Produces (plugin): card `com.decker.utilities.stopwatch` (icon `fas:stopwatch`), plugin-scoped `stopwatch_toggle`, `stopwatch_reset`; press → toggle, double/long → reset. Face: `fmt_ms(elapsed)`; repaint at 1 Hz while running.

- [ ] **Step 1: Write failing tests** — start/pause/resume accumulates correctly with a fake clock; reset zeroes and stops; face text `0:00`, `1:05`, `1:00:00`.
- [ ] **Step 2: Run, expect FAIL.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(utilities): Stopwatch card"`

---

### Task 9: README, platform table, packaging

**Files:** `README.md` (platform table row for `utilities (com.decker.utilities)` with footnotes: Linux external monitors need `ddcutil` + `i2c-dev` module + `i2c` group; macOS: internal display only, Lock needs Accessibility; tier 3 lock needs a logind-aware locker), `docs/platform-support.md` if it lists plugins; plugin `README`/description in manifest.

- [ ] **Step 1:** Update docs.
- [ ] **Step 2:** `uv run pytest` (all), `uv run ruff check .`, `uv run python -m tools.pack_all` → `dist/com.decker.utilities-1.0.0.deckerplugin` exists without `tests/`; `uv run python -m tools.check_versions origin/main` passes.
- [ ] **Step 3:** Manual check on the dev machine: install the package in a running Decker 0.7.2, place each card, exercise each gesture once (sleep/lock last).
- [ ] **Step 4: Commit** — `git commit -m "docs(utilities): README and platform table"`
