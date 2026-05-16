from __future__ import annotations

from dataclasses import dataclass

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

    def capture_sweep(self) -> CapturedMeasurement:
        for command in self._commands.prepare_measurement_commands:
            self._transport.write(command)

        nf_values = _parse_csv_floats(self._transport.query(self._commands.nf_data_query))
        gain_values = _parse_csv_floats(self._transport.query(self._commands.gain_data_query))

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
        summary = self._build_summary(nf_trace, gain_trace)
        return CapturedMeasurement(nf_trace=nf_trace, gain_trace=gain_trace, summary=summary)

    def _check_configuration_response(self, check: ConfigurationCheck, response: str) -> bool:
        if check.expected is None:
            return True
        if check.match == "contains":
            return check.expected in response
        return response == check.expected

    def _build_summary(self, nf_trace: SweepTrace, gain_trace: SweepTrace) -> MeasurementSummary:
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
