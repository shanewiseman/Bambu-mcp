from __future__ import annotations

import pytest

from bambu_mcp.capabilities import (
    EXTERNAL_SPOOL_SENTINEL,
    OPERATIONS,
    X2DAdapter,
    firmware_tuple,
    operation_named,
)
from bambu_mcp.errors import SafetyError, ValidationError
from bambu_mcp.schemas import MaterialRoute, SliceSettings
from bambu_mcp.state import deep_merge


def test_deep_merge_sparse_reports_without_mutation() -> None:
    current = {"print": {"ams": {"trays": [1, 2]}, "temp": 20}, "x": 1}
    update = {"print": {"temp": 21, "hms": []}}
    merged = deep_merge(current, update)
    assert merged == {
        "print": {"ams": {"trays": [1, 2]}, "temp": 21, "hms": []},
        "x": 1,
    }
    update["print"]["hms"].append("changed")
    assert merged["print"]["hms"] == []
    assert current["print"]["temp"] == 20
    assert deep_merge({"list": [1]}, {"list": [2]}) == {"list": [2]}


def test_firmware_and_capability_snapshot() -> None:
    assert firmware_tuple("01.02.03.04") == (1, 2, 3, 4)
    assert firmware_tuple("v2.7-beta") == (2, 7)
    assert firmware_tuple(None) == ()
    adapter = X2DAdapter()
    capabilities = adapter.capabilities("01.00.00.00")
    assert capabilities["dual_nozzle"] is True
    assert capabilities["lights"] == ["chamber_light", "work_light"]
    assert capabilities["operations"]["pause"]["risk"] == "routine"
    assert "firmware_upgrade" not in capabilities["operations"]
    assert adapter.operation_available(OPERATIONS["pause"], None)


def test_material_mapping_single_dual_external_and_fts() -> None:
    adapter = X2DAdapter()
    assert adapter.material_mapping(SliceSettings()) == {
        "ams_mapping": [],
        "ams_mapping2": [],
        "nozzle_mapping": [],
        "use_ams": False,
        "fts_mapping": [],
    }
    settings = SliceSettings(
        nozzle_diameters=(0.4, 0.4),
        filament_profiles=("PLA", "PETG", "Support"),
        material_routes=(
            MaterialRoute(filament_index=0, nozzle="left", ams_slot=3),
            MaterialRoute(
                filament_index=1,
                nozzle="right",
                external_spool=True,
                fts_channel=1,
            ),
            MaterialRoute(filament_index=2, nozzle="right", ams_slot=7),
        ),
    )
    mapping = adapter.material_mapping(settings)
    assert mapping["ams_mapping"] == [3, -1, -1]
    assert mapping["ams_mapping2"] == [-1, EXTERNAL_SPOOL_SENTINEL, 7]
    assert mapping["nozzle_mapping"] == [0, 1, 1]
    assert mapping["fts_mapping"] == [-1, 1, -1]
    assert mapping["use_ams"] is True


def test_material_mapping_rejects_missing_duplicate_and_unmapped_multi() -> None:
    adapter = X2DAdapter()
    with pytest.raises(ValidationError, match="explicit routes"):
        adapter.material_mapping(SliceSettings(filament_profiles=("A", "B")))
    missing = SliceSettings(
        filament_profiles=("A", "B"),
        material_routes=(MaterialRoute(filament_index=0, nozzle="left", ams_slot=0),),
    )
    with pytest.raises(ValidationError, match="every sliced"):
        adapter.material_mapping(missing)
    duplicate = SliceSettings(
        filament_profiles=("A",),
        material_routes=(
            MaterialRoute(filament_index=0, nozzle="left", ams_slot=0),
            MaterialRoute(filament_index=0, nozzle="right", ams_slot=1),
        ),
    )
    with pytest.raises(ValidationError, match="only once"):
        adapter.material_mapping(duplicate)


def test_write_gate_and_operation_catalog() -> None:
    adapter = X2DAdapter()
    with pytest.raises(SafetyError, match="Developer"):
        adapter.require_write_allowed(
            model="X2D",
            hardware_verified=True,
            allow_unverified_x2d_writes=False,
            developer_mode=False,
        )
    with pytest.raises(SafetyError, match="ALLOW_UNVERIFIED"):
        adapter.require_write_allowed(
            model="X2D",
            hardware_verified=False,
            allow_unverified_x2d_writes=False,
            developer_mode=True,
        )
    adapter.require_write_allowed(
        model="X2D",
        hardware_verified=False,
        allow_unverified_x2d_writes=True,
        developer_mode=True,
    )
    assert operation_named("pause", experimental_enabled=False).command == "pause"
    with pytest.raises(SafetyError, match="disabled"):
        operation_named("raw_gcode", experimental_enabled=False)
    assert operation_named("raw_gcode", experimental_enabled=True).risk.value == "experimental"
    with pytest.raises(SafetyError, match="never"):
        operation_named("firmware_upgrade", experimental_enabled=True)
    with pytest.raises(ValidationError, match="not catalogued"):
        operation_named("unknown", experimental_enabled=True)
