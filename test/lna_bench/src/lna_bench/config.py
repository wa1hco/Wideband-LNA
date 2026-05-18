from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib


@dataclass(slots=True)
class StationInfo:
    name: str
    output_dir: Path
    database_path: Path


@dataclass(slots=True)
class VisaConfig:
    resource_name: str
    backend: str | None
    timeout_ms: int
    read_termination: str
    write_termination: str


@dataclass(slots=True)
class SweepConfig:
    start_hz: float
    stop_hz: float
    points: int
    key_frequencies_hz: list[float]


@dataclass(slots=True)
class CommandConfig:
    identify_query: str
    opc_query: str
    prepare_measurement_commands: list[str]
    nf_data_query: str
    gain_data_query: str
    frequency_data_query: str | None


@dataclass(slots=True)
class InstrumentControlConfig:
    acquire_commands: list[str]
    release_commands: list[str]
    release_to_local: bool


@dataclass(slots=True)
class CalibrationConfig:
    calibration_date: str
    calibration_method: str
    fixture_loss_db: float


@dataclass(slots=True)
class ConfigurationCheck:
    name: str
    query: str
    expected: str | None
    match: str


@dataclass(slots=True)
class InstrumentConfigurationConfig:
    apply_commands: list[str]
    verify_checks: list[ConfigurationCheck]
    fail_on_mismatch: bool


@dataclass(slots=True)
class RuntimeConfig:
    single_instance: bool
    lock_stale_seconds: int


@dataclass(slots=True)
class AppConfig:
    station: StationInfo
    visa: VisaConfig
    sweep: SweepConfig
    commands: CommandConfig
    control: InstrumentControlConfig
    configuration: InstrumentConfigurationConfig
    runtime: RuntimeConfig
    calibration: CalibrationConfig


def _expand_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _get_required(section: dict[str, Any], key: str) -> Any:
    if key not in section:
        raise KeyError(f"Missing required config value: {key}")
    return section[key]


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    base_dir = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent
    station_section = raw.get("station", {})
    visa_section = raw.get("visa", {})
    sweep_section = raw.get("sweep", {})
    command_section = raw.get("commands", {})
    control_section = raw.get("control", {})
    configuration_section = raw.get("configuration", {})
    runtime_section = raw.get("runtime", {})
    calibration_section = raw.get("calibration", {})

    station = StationInfo(
        name=str(_get_required(station_section, "name")),
        output_dir=_expand_path(str(_get_required(station_section, "output_dir")), base_dir),
        database_path=_expand_path(str(_get_required(station_section, "database_path")), base_dir),
    )

    backend_value = str(visa_section.get("backend", "")).strip()
    visa = VisaConfig(
        resource_name=str(_get_required(visa_section, "resource_name")),
        backend=backend_value or None,
        timeout_ms=int(visa_section.get("timeout_ms", 30000)),
        read_termination=str(visa_section.get("read_termination", "\n")),
        write_termination=str(visa_section.get("write_termination", "\n")),
    )

    sweep = SweepConfig(
        start_hz=float(_get_required(sweep_section, "start_hz")),
        stop_hz=float(_get_required(sweep_section, "stop_hz")),
        points=int(_get_required(sweep_section, "points")),
        key_frequencies_hz=[float(value) for value in sweep_section.get("key_frequencies_hz", [])],
    )

    frequency_query = str(command_section.get("frequency_data_query", "")).strip() or None
    commands = CommandConfig(
        identify_query=str(command_section.get("identify_query", "*IDN?")),
        opc_query=str(command_section.get("opc_query", "*OPC?")),
        prepare_measurement_commands=[str(value) for value in command_section.get("prepare_measurement_commands", [])],
        nf_data_query=str(_get_required(command_section, "nf_data_query")),
        gain_data_query=str(_get_required(command_section, "gain_data_query")),
        frequency_data_query=frequency_query,
    )

    control = InstrumentControlConfig(
        acquire_commands=[str(value) for value in control_section.get("acquire_commands", [])],
        release_commands=[str(value) for value in control_section.get("release_commands", [])],
        release_to_local=bool(control_section.get("release_to_local", True)),
    )

    verify_checks_raw = configuration_section.get("verify_checks", [])
    verify_checks: list[ConfigurationCheck] = []
    for index, check in enumerate(verify_checks_raw):
        if not isinstance(check, dict):
            raise TypeError("configuration.verify_checks entries must be TOML inline tables")
        name = str(check.get("name", f"check_{index + 1}"))
        query = str(_get_required(check, "query"))
        expected_value = check.get("expected")
        expected = str(expected_value) if expected_value is not None else None
        match = str(check.get("match", "exact")).lower()
        if match not in {"exact", "contains"}:
            raise ValueError("configuration.verify_checks.match must be 'exact' or 'contains'")
        verify_checks.append(ConfigurationCheck(name=name, query=query, expected=expected, match=match))

    configuration = InstrumentConfigurationConfig(
        apply_commands=[str(value) for value in configuration_section.get("apply_commands", [])],
        verify_checks=verify_checks,
        fail_on_mismatch=bool(configuration_section.get("fail_on_mismatch", True)),
    )

    runtime = RuntimeConfig(
        single_instance=bool(runtime_section.get("single_instance", True)),
        lock_stale_seconds=int(runtime_section.get("lock_stale_seconds", 1800)),
    )

    calibration = CalibrationConfig(
        calibration_date=str(calibration_section.get("calibration_date", "")),
        calibration_method=str(calibration_section.get("calibration_method", "")),
        fixture_loss_db=float(calibration_section.get("fixture_loss_db", 0.0)),
    )

    return AppConfig(
        station=station,
        visa=visa,
        sweep=sweep,
        commands=commands,
        control=control,
        configuration=configuration,
        runtime=runtime,
        calibration=calibration,
    )
