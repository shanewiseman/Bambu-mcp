"""Fail if the independently distributed Python environment contains copyleft."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

FORBIDDEN = ("GNU GENERAL PUBLIC LICENSE", "GNU AFFERO", "AGPL", "GPLV")


def main() -> None:
    report_path = Path(sys.argv[1])
    report: list[dict[str, Any]] = json.loads(report_path.read_text(encoding="utf-8"))
    violations = []
    for package in report:
        license_name = str(package.get("License", "")).upper()
        if any(marker in license_name for marker in FORBIDDEN):
            violations.append(f"{package.get('Name')} {package.get('Version')}: {license_name}")
    if violations:
        raise SystemExit("copyleft dependency crossed the core boundary:\n" + "\n".join(violations))
    print(f"checked {len(report)} installed packages; no GPL/AGPL license label found")


if __name__ == "__main__":
    main()
