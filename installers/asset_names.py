"""Single source of truth for installer asset filenames.

Today the same naming convention is duplicated in three places:

  - ``installers/windows/build_installer.ps1`` — produces
    ``chika-setup-{v}.exe``
  - ``installers/macos/build_pkg.sh`` — produces ``Chika-{v}.pkg``
  - ``installers/linux/build_deb.sh`` — produces ``chika_{v}_all.deb``
  - ``chika/_cli/update.py::_expected_asset_name`` — has to know all
    three so ``chika update`` can find the right asset on
    releases/latest

If they ever drift, ``chika update`` silently can't find its asset
and silently fails the auto-update. This module is the single source.
The build scripts read it via ``python -m installers.asset_names <kind>
<version>``; the update module imports the function directly.
"""
from __future__ import annotations

import argparse
import sys
from typing import Final

# Kind → format-string template. Keep in lock-step with what each
# build script produces. Changing any of these is a coordinated
# change to the build script + the update module + the test suite.
ASSET_TEMPLATES: Final[dict[str, str]] = {
    "windows_installer": "chika-setup-{version}.exe",
    "macos_installer":   "Chika-{version}.pkg",
    "linux_deb":         "chika_{version}_all.deb",
    # linux_universal updates by re-running install.sh — no asset.
}


def expected_asset_name(kind: str, version: str) -> str | None:
    """Return the asset filename for ``kind`` at ``version``, or None
    if the install kind doesn't ship a single-file asset."""
    template = ASSET_TEMPLATES.get(kind)
    if template is None:
        return None
    return template.format(version=version)


def all_kinds() -> list[str]:
    return sorted(ASSET_TEMPLATES.keys())


def main(argv: list[str] | None = None) -> int:
    """CLI surface so shell build scripts can read the canonical names.

    Usage from bash:
        ASSET=$(python -m installers.asset_names windows_installer 2.0.5)
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("kind", choices=sorted(ASSET_TEMPLATES.keys()))
    parser.add_argument("version")
    args = parser.parse_args(argv)
    name = expected_asset_name(args.kind, args.version)
    if name is None:
        return 1
    print(name)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
