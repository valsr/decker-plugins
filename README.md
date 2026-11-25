# decker-plugins

Plugins for [Decker](https://github.com/valsr/decker) and the tooling that tests, packages and publishes them. Packages
are GitHub Releases, the index is served by GitHub Pages at <https://valsr.github.io/decker-plugins/index.json>.

## Add this repository to Decker

It is Decker's default repository. If you removed it: Settings, Plugins, Repositories, "Add…", then enter
`https://valsr.github.io/decker-plugins/index.json`. Only add repositories you trust: plugins run with your user's
permissions. See Decker's `docs/plugins/repositories.md`.

## Requirements and Font Awesome

The plugins here use manifest format 3; Pages and Profiles declare `"decker": ">=0.8"` because they contribute
presets (see below). Counter (2.0.2) and Utilities (2.1.2) declare `">=0.8.1"`: their cards list
their own actions in `cards[].actions`, which Decker 0.8.1 introduced. The former Fontawesome plugin (`com.decker.fontawesome`) is retired: Font
Awesome Free 7.3.1 is built into Decker 0.7 as the Built-In icon packs, referenced as `fab:<name>` (brands),
`far:<name>` (regular) and `fas:<name>` (solid), for example `fas:play`. Existing `pack:com.decker.fontawesome.*`
references need to be switched to those forms.

## Layout

- `plugins/<plugin-id>/`: the plugin source as accepted by Decker's plugin packer, with its own `tests/`. The folder
  name must equal the manifest `id`.
- `tools/`: `pack_all.py`, `check_versions.py`, `release_meta.py`, `build_index.py`. Tests in `tests/tools/`.
- Decker is installed from git at a pinned commit (see `pyproject.toml`) for its packaging and index parsing code.

## Add or change a plugin

1. Create `plugins/<plugin-id>/` with a `manifest.json` (and tests under `tests/`).
2. Run the tests: `uv run pytest plugins/<plugin-id>` (everything: `uv run pytest`).
3. Package it locally: `uv run python -m tools.pack_all` writes `dist/<id>-<version>.deckerplugin` (without `tests/`).
4. Open a pull request.

### Platform support

Every plugin change must also update the [platform table](#platform-support) below (Decker has its own table for the
core). Plugins declare `platforms`/`linux` in their manifest; see [docs/platform-support.md](docs/platform-support.md).

### Version rule

Any change below `plugins/<id>/` needs a manifest `version` (semver `x.y.z`) greater than the highest `<id>-v*` git tag.
The version must be valid semver and also parseable as a PEP 440 version (no `-rc`-style suffixes unless PEP 440 accepts them). A plugin with no tag yet passes. CI runs `python -m tools.check_versions origin/<base>` on pull requests and fails otherwise.
A published version is never changed: the same id and version must always be the same bytes.

## Utilities

`com.decker.utilities` (2.1.2, needs Decker 0.8.1 or newer) bundles utility cards and actions.

Cards: Counter, Brightness Level, Deck Brightness Level, Sleep, Timer and Stopwatch.

Presets (Cards pane in the sidebar, drop onto a key): Brightness Up/Down, Deck Brightness Up/Down and Lock screen.
The Page and Profile actions remain as global actions; Pages and Profiles offer presets for the same job.

- Brightness Level shows the display brightness (press up, double press down, long press set 75%); its `monitor`
  setting picks the monitor. The Deck variant controls the Stream Deck's own brightness.
- Sleep: press sleeps now (or cancels a running countdown), double press sleeps in 1 minute, long press in 10.
- Timer (minutes, seconds, progress circle or bar, solid, two-colour or gradient) and Stopwatch: press starts or pauses,
  double or long press resets.
- The Counter card offers the same functions as the standalone Counter. Pages and Profiles (3.1.1) ship global
  actions (`next`, `previous`, `goto`) and presets (Next/Previous/Go to page or profile, Page Name, Page Count, Profile
  Name) and no cards.

Global actions: `brightness`, `deck-brightness`, `sleep`, `lock`, `page`, `profile` and `sleep-cancel` (cancels every
running Sleep countdown; countdowns keep running when their key is removed or its page is left). Plugin-scoped actions
used by the cards: `counter-increment`, `counter-decrement`, `counter-reset`, `sleep-press`, `sleep-after`,
`timer-toggle`, `timer-reset`, `stopwatch-toggle`, `stopwatch-reset`.

Variables: `brightness_level`, `brightness_level_{monitor}` (1-based), `deck_brightness_level`,
`deck_brightness_level_{device}` and `sleep_in`.

Caveats:

- The `monitor` setting of a Brightness Level card steers its bindings: an explicit `all` binding on that card follows
  the card's setting.
- Timers, Sleep countdowns and stopwatches are lost when the plugin restarts. They measure real time across system
  sleep (on a clock that keeps counting while the machine is suspended). One that ends during system sleep is not fired
  late: a timer finishes quietly on wake, a Sleep countdown is dropped (more than 5 seconds late).
- Platform requirements (external monitors, macOS Accessibility, Linux locker) are in the
  [platform table](#platform-support). None of it is verified on real hardware yet.

## Publishing

On every push to `main`, `publish.yml` packs all plugins; for each version without a release it creates the release
`<id>-v<version>` with the `.deckerplugin` and its `<package>.json` sidecar (the index version entry plus the plugin
`id`). Existing releases are never edited. It then downloads every release's sidecar, builds `index.json` and
`icons/<id>.png` (for file icons; a built-in `fas:`/`far:`/`fab:` ref is written into the index as is) with
`python -m tools.build_index` and deploys them to GitHub Pages. Enable Pages with the "GitHub Actions"
source in the repository settings.

Owner and repository come from `GITHUB_REPOSITORY` in CI and default to `valsr/decker-plugins`.

## Platform support

✅ works (verified by the maintainer or by CI)[^1] · ⚠️ partial or not verified · ❌ not supported

| Plugin | Linux (Arch/Plasma/Wayland) | Linux (Ubuntu/Debian/Fedora/GNOME) | Linux (other) | Windows | macOS |
|--------|------|------|------|------|------|
| counter (`com.decker.counter`)[^2] | ✅[^4] | ✅[^3] | ⚠️ | ✅ | ✅ |
| pages (`com.decker.pages`) | ✅[^4] | ✅[^3] | ⚠️ | ✅ | ✅ |
| profiles (`com.decker.profiles`) | ✅[^4] | ✅[^3] | ⚠️ | ✅ | ✅ |
| utilities (`com.decker.utilities`)[^5] | ⚠️[^6] | ⚠️[^6] | ⚠️[^7] | ⚠️[^8] | ⚠️[^9] |

[^1]: CI means the GitHub Actions workflow
    ([run 44573274250](https://github.com/valsr/decker-plugins/actions/runs/44573274250), head `992532b`) was green on
    `ubuntu-latest`, `windows-latest`, `macos-latest` and in `fedora:latest` and `archlinux:latest` containers. On each
    it ran the tool tests (33 passed) and the
    Counter suite (19 passed) against the pinned Decker. The pages (21) and profiles (23) counts are from a local run
    on `feat/card-action-split`; CI for that branch is pending. The Counter run included Counter's font path with the
    bundled DejaVu Sans Bold. Plugin packaging runs on Linux only. CI does not
    cover a real Stream Deck, the real Decker UI, or a real plugin process under the Decker supervisor on any OS.
[^2]: Since 1.1.0 Counter draws with Decker's bundled DejaVu Sans Bold through the SDK (`decker_plugin_sdk.fonts`) on
    every OS, and falls back to Pillow's default font on a Decker without `decker_plugin_sdk.fonts`.
[^3]: The `ubuntu-latest` runner and the Fedora container (a blocking check) cover the plugin tests on Ubuntu and
    Fedora, not the GNOME desktop specifically.
[^4]: The Arch Linux container runs the same tests as an advisory check (`continue-on-error`, since a rolling release
    can break without a change here). It covers Arch, not the Plasma desktop or Wayland, and the maintainer has not
    yet used the plugins there, so the cell is ✅ on CI evidence alone.
[^5]: Utilities bundles Counter, brightness, sleep, timer and stopwatch cards with lock, page and profile actions; see
    [Utilities](#utilities). Its tests run in CI, but the OS-facing parts (display brightness, sleep, lock) are not
    verified on real hardware on any OS yet.
[^6]: Linux external monitors need `ddcutil`, the `i2c-dev` kernel module and membership of the `i2c` group (laptop
    panels work without them).
[^7]: As above, plus Lock needs a logind-aware locker (`loginctl lock-session` must reach a running screen locker).
[^8]: Windows uses `screen-brightness-control` (WMI, DDC/CI); not verified.
[^9]: macOS controls the internal display only, and Lock needs the Accessibility permission for "Decker (or the
    terminal running it)". On a Mac without a built-in display (mini, Studio, Pro) "Built-in display" is still listed
    and the brightness actions fail with a clear error.

Pages and Profiles use no OS APIs. Only the Utilities manifest declares `platforms` (all three: `linux`, `windows`,
`macos`) and no manifest has a `linux` key, so no manifest restricts any platform; the table above records what has
been verified, not what the manifests restrict.

