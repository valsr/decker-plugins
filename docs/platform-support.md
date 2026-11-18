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
| Not verified | Nobody has tried it; it may or may not work |
| Not audited | The plugin has not been assessed for this platform yet (the initial state of every cell) |

## Plugins

| Plugin | Linux (Arch/Plasma/Wayland) | Linux (Ubuntu/Debian/Fedora/GNOME) | Linux (other) | Windows | macOS |
|--------|------|------|------|------|------|
| counter (`com.decker.counter`) | Not audited | Not audited | Not audited | Not audited | Not audited |
| fontawesome (`com.decker.fontawesome`) | Not audited | Not audited | Not audited | Not audited | Not audited |
| icon (`com.decker.icon`) | Not audited | Not audited | Not audited | Not audited | Not audited |
| pages (`com.decker.pages`) | Not audited | Not audited | Not audited | Not audited | Not audited |
| profiles (`com.decker.profiles`) | Not audited | Not audited | Not audited | Not audited | Not audited |

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
