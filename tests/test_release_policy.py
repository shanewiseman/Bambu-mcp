from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

LICENSE_CHECKER = Path(__file__).parents[1] / "scripts" / "check_dependency_licenses.py"


def write_license_report(path: Path, license_name: str) -> None:
    path.write_text(
        json.dumps([{"Name": "fixture", "Version": "1.0", "License": license_name}]),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "license_name",
    [
        "GPL-3.0-only",
        "GPL-2.0-or-later",
        "AGPL-3.0-only",
        "GNU General Public License v2",
        "GNU Affero General Public License v3",
        "GPLv3",
    ],
)
def test_license_checker_rejects_gpl_and_agpl_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    license_name: str,
) -> None:
    report = tmp_path / "licenses.json"
    write_license_report(report, license_name)
    monkeypatch.setattr("sys.argv", ["check_dependency_licenses.py", str(report)])

    with pytest.raises(SystemExit, match="copyleft dependency"):
        runpy.run_path(str(LICENSE_CHECKER), run_name="__main__")


@pytest.mark.parametrize(
    "license_name",
    [
        "MIT",
        "BSD-3-Clause",
        "LGPL-3.0-only",
        "GNU Lesser General Public License v3",
        "Mozilla Public License 2.0",
        "",
    ],
)
def test_license_checker_accepts_non_gpl_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    license_name: str,
) -> None:
    report = tmp_path / "licenses.json"
    write_license_report(report, license_name)
    monkeypatch.setattr("sys.argv", ["check_dependency_licenses.py", str(report)])

    runpy.run_path(str(LICENSE_CHECKER), run_name="__main__")

    assert "checked 1 installed package" in capsys.readouterr().out
