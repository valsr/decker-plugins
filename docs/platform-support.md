# Platform support

**Standing rule:** every plugin change must update this table in the same change. Decker itself keeps its own
features x platforms table in `docs/platform-support.md` of the [Decker repository](https://github.com/valsr/decker);
that one covers the core, this one covers the plugins in this repository.

A plugin should target all five platform tiers below. It may skip a platform when porting is too onerous, but it must
say so in its manifest (see [Declaring platforms](#declaring-platforms)) so users can see and filter on it.

## Priority tiers

1. Linux (Arch/Manjaro, Plasma, Wayland): the primary target.
2. Linux (Ubuntu/Debian/Fedora, GNOME): parity with the primary target.
3. Linux (other): 90-100% of the functionality.
4. Windows: 75%+ of the functionality.
5. macOS: 75%+ of the functionality.

## Legend

| Value | Meaning |
|-------|---------|
| Yes | Works, and the author has verified it on that platform |
| Partial | Works with known gaps; a footnote names the cause |
| Planned | Not working yet, on the roadmap |
| No | The code clearly cannot work there today |
| CI | Verified by the CI matrix on that OS; says nothing about real hardware or the Decker UI[^1] |
| Not verified | Nobody has tried it; it may or may not work |
| Not audited | The plugin has not been assessed for this platform yet (the initial state of every cell) |

## Plugins

| Plugin | Linux (Arch/Plasma/Wayland) | Linux (Ubuntu/Debian/Fedora/GNOME) | Linux (other) | Windows | macOS |
|--------|------|------|------|------|------|
| counter (`com.decker.counter`)[^2] | Not verified | CI[^3] | Not verified | CI | CI |
| fontawesome (`com.decker.fontawesome`) | Not verified | CI[^3] | Not verified | CI | CI |
| icon (`com.decker.icon`) | Not verified | CI[^3] | Not verified | CI | CI |
| pages (`com.decker.pages`) | Not verified | CI[^3] | Not verified | CI | CI |
| profiles (`com.decker.profiles`) | Not verified | CI[^3] | Not verified | CI | CI |

[^1]: CI means the GitHub Actions workflow
    ([run 44562413596](https://github.com/valsr/decker-plugins/actions/runs/44562413596), head `ae2eb7c`) was green on
    `ubuntu-latest`, `windows-latest` and `macos-latest`. On each OS it ran the tool tests (33 passed) and the five
    plugin suites (counter 19, fontawesome 9, icon 8, pages 36, profiles 30 passed) against the pinned Decker,
    including Counter's font path with the bundled DejaVu Sans Bold. Plugin packaging runs on Linux only. CI does not
    cover a real Stream Deck, the real Decker UI, or a real plugin process under the Decker supervisor on any OS.
[^2]: Since 1.1.0 Counter draws with Decker's bundled DejaVu Sans Bold through the SDK (`decker_plugin_sdk.fonts`) on
    every OS, and falls back to Pillow's default font on a Decker without `decker_plugin_sdk.fonts`.
[^3]: The `ubuntu-latest` runner covers the plugin tests on Ubuntu, not the GNOME desktop specifically.

Pages, Profiles, Icon and Font Awesome use no OS APIs. No manifest declares `platforms` or `linux`, which means all
platforms; the table above records what has been verified, not what the manifests restrict.

## Declaring platforms

A manifest declares support with two optional fields (the full rules are in Decker's
[package and manifest](https://github.com/valsr/decker/blob/main/docs/plugins/package-and-manifest.md#platforms)
reference):

```json
{ "platforms": ["linux", "windows"], "linux": { "desktops": ["kde", "gnome"], "sessions": ["wayland"] } }
```

- `platforms`: non-empty list of OS names (`linux`, `windows`, `macos`). Omitted means all platforms.
- `linux`: narrows Linux support with `desktops` (`kde`, `gnome`, `other`) and `sessions` (`wayland`, `x11`). Only
  allowed when `platforms` is absent or includes `linux`.
- Declare only platforms you have actually tested, and keep the table above in sync.
- The release tooling copies both fields into the index version entry, so the Decker repository browser can filter on
  them. A mismatch never blocks installation; the client shows a "Not supported" badge.
