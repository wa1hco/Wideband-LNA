from __future__ import annotations

from dataclasses import dataclass
import time

from lna_bench.config import (
    CommandConfig,
    ConfigurationCheck,
    InstrumentConfigurationConfig,
    InstrumentControlConfig,
    SweepConfig,
)
from lna_bench.models import MeasurementSummary, SweepTrace
from lna_bench.transport import VisaTransport


def _parse_csv_floats(payload: str) -> list[float]:
    values = [item.strip().rstrip("\x00") for item in payload.replace("\n", ",").split(",")]
    return [float(item) for item in values if item]


def _linspace(start: float, stop: float, points: int) -> list[float]:
    if points <= 1:
        return [start]
    step = (stop - start) / (points - 1)
    return [start + (step * index) for index in range(points)]


def _nearest_value(frequencies_hz: list[float], values: list[float], target_hz: float) -> float:
    best_index = min(range(len(frequencies_hz)), key=lambda idx: abs(frequencies_hz[idx] - target_hz))
    return values[best_index]


@dataclass(slots=True)
class CapturedMeasurement:
    nf_trace: SweepTrace
    gain_trace: SweepTrace
    summary: MeasurementSummary
    measurement_bandwidth_hz: float = 0.0
    key_point_averages: int = 0


@dataclass(slots=True)
class ConfigurationCheckResult:
    name: str
    query: str
    response: str
    expected: str | None
    passed: bool


class N8973AController:
    def __init__(
        self,
        transport: VisaTransport,
        sweep: SweepConfig,
        commands: CommandConfig,
        control: InstrumentControlConfig,
        configuration: InstrumentConfigurationConfig,
    ) -> None:
        self._transport = transport
        self._sweep = sweep
        self._commands = commands
        self._control = control
        self._configuration = configuration

    def identify(self) -> str:
        return self._transport.query(self._commands.identify_query)

    def acquire_computer_control(self) -> None:
        for command in self._control.acquire_commands:
            self._transport.write(command)

    def release_to_user_control(self) -> None:
        for command in self._control.release_commands:
            self._transport.write(command)
        if self._control.release_to_local:
            self._transport.release_to_local()

    def apply_configuration(self) -> None:
        for command in self._configuration.apply_commands:
            self._transport.write(command)
        # Push sweep params from [sweep] so the config is the single source of truth.
        self._transport.write(f"SENS:FREQ:STAR {self._sweep.start_hz:.0f}")
        self._transport.write(f"SENS:FREQ:STOP {self._sweep.stop_hz:.0f}")
        self._transport.write(f"SENS:SWE:POIN {self._sweep.points}")

    def verify_configuration(self) -> list[ConfigurationCheckResult]:
        results: list[ConfigurationCheckResult] = []
        for check in self._configuration.verify_checks:
            response = self._transport.query(check.query).strip()
            passed = self._check_configuration_response(check, response)
            results.append(
                ConfigurationCheckResult(
                    name=check.name,
                    query=check.query,
                    response=response,
                    expected=check.expected,
                    passed=passed,
                )
            )
        return results

    def should_fail_on_configuration_mismatch(self) -> bool:
        return self._configuration.fail_on_mismatch

    def snapshot_state(self) -> str | None:
        if not self._commands.state_snapshot_query:
            return None
        return self._transport.query(self._commands.state_snapshot_query)

    def restore_state(self, snapshot: str | None) -> None:
        if snapshot is None:
            return
        restore_command = self._commands.state_restore_command
        if restore_command:
            command = restore_command.format(state=snapshot)
        else:
            command = snapshot
        if command.strip():
            self._transport.write(command)
            if self._commands.opc_query:
                self._transport.query(self._commands.opc_query)

    def capture_sweep(self) -> CapturedMeasurement:
        for command in self._commands.prepare_measurement_commands:
            self._transport.write(command)

        # Deterministic single-shot acquisition: abort any running sweep, trigger one
        # fresh sweep with the current config, wait for it to complete via *OPC?, then
        # fetch. Removes the timing race that made FETC return empty data after
        # apply_configuration pushed new sweep params. Resumes INIT:CONT ON at the end
        # so the front panel keeps updating between Records.
        self._transport.write("ABOR")
        self._transport.write("INIT:CONT OFF")
        self._transport.write("INIT:IMM")
        self._transport.query("*OPC?")

        nf_values = _parse_csv_floats(self._transport.query(self._commands.nf_data_query))
        gain_values = _parse_csv_floats(self._transport.query(self._commands.gain_data_query))

        self._transport.write("INIT:CONT ON")

        if not nf_values or not gain_values:
            raise ValueError(
                "Broadband sweep returned no data after triggered acquisition. "
                "Check the instrument front panel for an error condition."
            )

        if len(nf_values) != len(gain_values):
            raise ValueError(
                f"NF and gain traces must have the same number of points; got {len(nf_values)} and {len(gain_values)}"
            )

        if self._commands.frequency_data_query:
            frequencies = _parse_csv_floats(self._transport.query(self._commands.frequency_data_query))
        else:
            frequencies = _linspace(self._sweep.start_hz, self._sweep.stop_hz, len(nf_values))

        if len(frequencies) != len(nf_values):
            raise ValueError(
                f"Frequency axis length must match data length; got {len(frequencies)} and {len(nf_values)}"
            )

        nf_trace = SweepTrace(frequencies_hz=frequencies, values=nf_values, unit="dB", label="Noise Figure")
        gain_trace = SweepTrace(frequencies_hz=frequencies, values=gain_values, unit="dB", label="Gain")
        direct_key_points, key_point_meta = self._capture_key_points_direct()
        summary = self._build_summary(nf_trace, gain_trace, key_points_override=direct_key_points)
        return CapturedMeasurement(
            nf_trace=nf_trace,
            gain_trace=gain_trace,
            summary=summary,
            measurement_bandwidth_hz=key_point_meta[0],
            key_point_averages=key_point_meta[1],
        )

    def _capture_key_points_direct(self) -> tuple[dict[str, dict[str, float]] | None, tuple[float, int]]:
        if not (
            self._commands.key_point_set_frequency_command
            and self._commands.key_point_nf_query
            and self._commands.key_point_gain_query
        ):
            return None, (0.0, 0)

        # Narrow-sweep span at each key freq. The N8973A enforces a non-zero span and POIN>=2,
        # so a single-point measurement isn't possible. 1 MHz keeps STAR exactly on target.
        KEY_POINT_SPAN_HZ = 1_000_000

        measurement_bandwidth_hz = 0.0
        key_point_averages = 0
        key_points: dict[str, dict[str, float]] = {}
        for target_hz in self._sweep.key_frequencies_hz:
            context = {
                "frequency_hz": target_hz,
                "frequency_mhz": target_hz / 1_000_000.0,
                "frequency_ghz": target_hz / 1_000_000_000.0,
                "frequency_hz_high": target_hz + KEY_POINT_SPAN_HZ,
            }
            set_frequency_command = self._commands.key_point_set_frequency_command.format(**context)
            nf_query = self._commands.key_point_nf_query.format(**context)
            gain_query = self._commands.key_point_gain_query.format(**context)

            self._transport.write(set_frequency_command)
            if self._commands.opc_query:
                self._transport.query(self._commands.opc_query)
            # Read back what the instrument actually applied (BW may quantize, COUN may differ).
            if measurement_bandwidth_hz == 0.0:
                try:
                    measurement_bandwidth_hz = float(self._transport.query("SENS:BAND:RES?"))
                    key_point_averages = int(float(self._transport.query("SENS:AVER:COUN?")))
                except Exception:
                    pass
            if self._commands.key_point_settle_ms > 0:
                time.sleep(self._commands.key_point_settle_ms / 1000.0)

            nf_values = _parse_csv_floats(self._transport.query(nf_query))
            gain_values = _parse_csv_floats(self._transport.query(gain_query))
            if not nf_values or not gain_values:
                raise ValueError(f"Direct key-point command returned no data at {target_hz} Hz")

            key = f"{target_hz / 1_000_000_000:.3f} GHz"
            key_points[key] = {
                "nf_db": nf_values[0],
                "gain_db": gain_values[0],
            }

        # Restore broadband sweep so the front panel returns to a useful state and the next
        # capture_sweep doesn't read stale narrow-sweep data.
        self.apply_configuration()
        return key_points, (measurement_bandwidth_hz, key_point_averages)

    def _check_configuration_response(self, check: ConfigurationCheck, response: str) -> bool:
        if check.expected is None:
            return True
        if check.match == "contains":
            return check.expected in response
        return response == check.expected

    def _build_summary(
        self,
        nf_trace: SweepTrace,
        gain_trace: SweepTrace,
        key_points_override: dict[str, dict[str, float]] | None = None,
    ) -> MeasurementSummary:
        if key_points_override is not None:
            key_points = key_points_override
        else:
            key_points: dict[str, dict[str, float]] = {}
            for target_hz in self._sweep.key_frequencies_hz:
                key = f"{target_hz / 1_000_000_000:.3f} GHz"
                key_points[key] = {
                    "nf_db": _nearest_value(nf_trace.frequencies_hz, nf_trace.values, target_hz),
                    "gain_db": _nearest_value(gain_trace.frequencies_hz, gain_trace.values, target_hz),
                }

        return MeasurementSummary(
            nf_min_db=min(nf_trace.values),
            nf_max_db=max(nf_trace.values),
            nf_avg_db=sum(nf_trace.values) / len(nf_trace.values),
            gain_min_db=min(gain_trace.values),
            gain_max_db=max(gain_trace.values),
            gain_avg_db=sum(gain_trace.values) / len(gain_trace.values),
            key_points=key_points,
        )
