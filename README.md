# decker-plugins

Plugins for [Decker](https://github.com/valsr/decker) and the tooling that tests, packages and publishes them. Packages
are GitHub Releases, the index is served by GitHub Pages at <https://valsr.github.io/decker-plugins/index.json>.

## Add this repository to Decker

It is Decker's default repository. If you removed it: Settings, Plugins, Repositories, "Add…", then enter
`https://valsr.github.io/decker-plugins/index.json`. Only add repositories you trust: plugins run with your user's
permissions. See Decker's `docs/plugins/repositories.md`.

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

## Publishing

On every push to `main`, `publish.yml` packs all plugins; for each version without a release it creates the release
`<id>-v<version>` with the `.deckerplugin` and its `<package>.json` sidecar (the index version entry plus the plugin
`id`). Existing releases are never edited. It then downloads every release's sidecar, builds `index.json` and
`icons/<id>.png` with `python -m tools.build_index` and deploys them to GitHub Pages. Enable Pages with the "GitHub Actions"
source in the repository settings.

Owner and repository come from `GITHUB_REPOSITORY` in CI and default to `valsr/decker-plugins`.

## Platform support

✅ works (verified by the maintainer or by CI)[^1] · ⚠️ partial or not verified · ❌ not supported

| Plugin | Linux (Arch/Plasma/Wayland) | Linux (Ubuntu/Debian/Fedora/GNOME) | Linux (other) | Windows | macOS |
|--------|------|------|------|------|------|
| counter (`com.decker.counter`)[^2] | ✅[^4] | ✅[^3] | ⚠️ | ✅ | ✅ |
| fontawesome (`com.decker.fontawesome`) | ✅[^4] | ✅[^3] | ⚠️ | ✅ | ✅ |
| pages (`com.decker.pages`) | ✅[^4] | ✅[^3] | ⚠️ | ✅ | ✅ |
| profiles (`com.decker.profiles`) | ✅[^4] | ✅[^3] | ⚠️ | ✅ | ✅ |

[^1]: CI means the GitHub Actions workflow
    ([run 44573274250](https://github.com/valsr/decker-plugins/actions/runs/44573274250), head `992532b`) was green on
    `ubuntu-latest`, `windows-latest`, `macos-latest` and in `fedora:latest` and `archlinux:latest` containers. On each
    it ran the tool tests (33 passed) and the five
    plugin suites (counter 19, fontawesome 9, icon 8, pages 36, profiles 30 passed) against the pinned Decker,
    including Counter's font path with the bundled DejaVu Sans Bold. Plugin packaging runs on Linux only. CI does not
    cover a real Stream Deck, the real Decker UI, or a real plugin process under the Decker supervisor on any OS.
[^2]: Since 1.1.0 Counter draws with Decker's bundled DejaVu Sans Bold through the SDK (`decker_plugin_sdk.fonts`) on
    every OS, and falls back to Pillow's default font on a Decker without `decker_plugin_sdk.fonts`.
[^3]: The `ubuntu-latest` runner and the Fedora container (a blocking check) cover the plugin tests on Ubuntu and
    Fedora, not the GNOME desktop specifically.
[^4]: The Arch Linux container runs the same tests as an advisory check (`continue-on-error`, since a rolling release
    can break without a change here). It covers Arch, not the Plasma desktop or Wayland, and the maintainer has not
    yet used the plugins there, so the cell is ✅ on CI evidence alone.

Pages, Profiles, Icon and Font Awesome use no OS APIs. No manifest declares `platforms` or `linux`, which means all
platforms; the table above records what has been verified, not what the manifests restrict.

