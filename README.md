# decker-plugins

Plugins for [Decker](https://github.com/valsr/Decker) and the tooling that tests, packages and publishes them. Packages
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
