from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class SweepTrace:
    frequencies_hz: list[float]
    values: list[float]
    unit: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SweepTrace":
        return cls(
            frequencies_hz=[float(value) for value in payload["frequencies_hz"]],
            values=[float(value) for value in payload["values"]],
            unit=str(payload["unit"]),
            label=str(payload["label"]),
        )


@dataclass(slots=True)
class MeasurementSummary:
    nf_min_db: float
    nf_max_db: float
    nf_avg_db: float
    gain_min_db: float
    gain_max_db: float
    gain_avg_db: float
    key_points: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MeasurementSummary":
        return cls(
            nf_min_db=float(payload["nf_min_db"]),
            nf_max_db=float(payload["nf_max_db"]),
            nf_avg_db=float(payload["nf_avg_db"]),
            gain_min_db=float(payload["gain_min_db"]),
            gain_max_db=float(payload["gain_max_db"]),
            gain_avg_db=float(payload["gain_avg_db"]),
            key_points={
                str(key): {inner_key: float(inner_value) for inner_key, inner_value in values.items()}
                for key, values in payload.get("key_points", {}).items()
            },
        )


@dataclass(slots=True)
class RunRecord:
    run_id: str
    serial_number: str
    preamp_version: str
    noise_head_id: str
    station_name: str
    instrument_id: str
    notes: str
    timestamp_utc: datetime
    is_retest: bool
    previous_run_id: str | None
    nf_trace: SweepTrace
    gain_trace: SweepTrace
    summary: MeasurementSummary
    operator: str = ""
    calibration_date: str = ""
    calibration_method: str = ""
    fixture_loss_db: float = 0.0
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["timestamp_utc"] = self.timestamp_utc.isoformat()
        return payload

    @classmethod
    def create(
        cls,
        *,
        serial_number: str,
        preamp_version: str,
        noise_head_id: str,
        station_name: str,
        instrument_id: str,
        notes: str,
        is_retest: bool,
        previous_run_id: str | None,
        nf_trace: SweepTrace,
        gain_trace: SweepTrace,
        summary: MeasurementSummary,
        operator: str = "",
        calibration_date: str = "",
        calibration_method: str = "",
        fixture_loss_db: float = 0.0,
    ) -> "RunRecord":
        return cls(
            run_id=str(uuid.uuid4()),
            serial_number=serial_number,
            preamp_version=preamp_version,
            noise_head_id=noise_head_id,
            station_name=station_name,
            instrument_id=instrument_id,
            notes=notes,
            timestamp_utc=utc_now(),
            is_retest=is_retest,
            previous_run_id=previous_run_id,
            nf_trace=nf_trace,
            gain_trace=gain_trace,
            summary=summary,
            operator=operator,
            calibration_date=calibration_date,
            calibration_method=calibration_method,
            fixture_loss_db=fixture_loss_db,
        )
