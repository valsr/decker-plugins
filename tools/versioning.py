"""Plugin version rules shared by the tools."""

from decker.plugin.manifest import is_valid_version
from packaging.version import InvalidVersion, Version


def parse_plugin_version(text: object) -> Version:
    """Parse a plugin version that is valid semver (Decker's manifest rule) and parseable by `packaging`.

    Decker sorts index versions with `packaging.version.Version`, so both rules must hold. Raises ValueError.
    """
    if not is_valid_version(text):
        raise ValueError(f"{text!r} is not a semantic version (x.y.z)")
    try:
        return Version(str(text))
    except InvalidVersion as exc:
        raise ValueError(f"{text!r} is not a valid PEP 440 version, which Decker needs to sort versions") from exc
