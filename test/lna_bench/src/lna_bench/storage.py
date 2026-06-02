from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from lna_bench.models import MeasurementSummary, RunRecord, SweepTrace


def _natural_key(value: str) -> list[object]:
    """Natural sort: 'SN2' < 'SN10' < 'SN10a'. Numeric chunks compare as ints."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


class RunRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    serial_number TEXT NOT NULL,
                    preamp_version TEXT NOT NULL,
                    noise_head_id TEXT NOT NULL,
                    station_name TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    is_retest INTEGER NOT NULL,
                    previous_run_id TEXT,
                    nf_trace_json TEXT NOT NULL,
                    gain_trace_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    operator TEXT DEFAULT '',
                    calibration_date TEXT DEFAULT '',
                    calibration_method TEXT DEFAULT '',
                    fixture_loss_db REAL DEFAULT 0.0,
                    measurement_bandwidth_hz REAL DEFAULT 0.0,
                    key_point_averages INTEGER DEFAULT 0,
                    report_path TEXT
                )
                """
            )
            for column_sql in (
                "ALTER TABLE runs ADD COLUMN measurement_bandwidth_hz REAL DEFAULT 0.0",
                "ALTER TABLE runs ADD COLUMN key_point_averages INTEGER DEFAULT 0",
            ):
                try:
                    conn.execute(column_sql)
                except sqlite3.OperationalError:
                    pass  # column already exists
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_serial_timestamp ON runs(serial_number, timestamp_utc DESC)"
            )
            conn.commit()

    def save_run(self, record: RunRecord) -> None:
        self.initialize()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id,
                    serial_number,
                    preamp_version,
                    noise_head_id,
                    station_name,
                    instrument_id,
                    notes,
                    timestamp_utc,
                    is_retest,
                    previous_run_id,
                    nf_trace_json,
                    gain_trace_json,
                    summary_json,
                    operator,
                    calibration_date,
                    calibration_method,
                    fixture_loss_db,
                    measurement_bandwidth_hz,
                    key_point_averages,
                    report_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.serial_number,
                    record.preamp_version,
                    record.noise_head_id,
                    record.station_name,
                    record.instrument_id,
                    record.notes,
                    record.timestamp_utc.isoformat(),
                    1 if record.is_retest else 0,
                    record.previous_run_id,
                    json.dumps(record.nf_trace.to_dict()),
                    json.dumps(record.gain_trace.to_dict()),
                    json.dumps(record.summary.to_dict()),
                    record.operator,
                    record.calibration_date,
                    record.calibration_method,
                    record.fixture_loss_db,
                    record.measurement_bandwidth_hz,
                    record.key_point_averages,
                    record.report_path,
                ),
            )
            conn.commit()

    def update_report_path(self, run_id: str, report_path: str) -> None:
        self.initialize()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("UPDATE runs SET report_path = ? WHERE run_id = ?", (report_path, run_id))
            conn.commit()

    def get_latest_run(self, serial_number: str) -> RunRecord | None:
        rows = self.list_runs(serial_number, limit=1)
        return rows[0] if rows else None

    def get_run_by_id(self, run_id: str) -> RunRecord | None:
        self.initialize()
        query = (
            "SELECT run_id, serial_number, preamp_version, noise_head_id, station_name, instrument_id, notes, "
            "timestamp_utc, is_retest, previous_run_id, nf_trace_json, gain_trace_json, summary_json, operator, "
            "calibration_date, calibration_method, fixture_loss_db, measurement_bandwidth_hz, key_point_averages, report_path "
            "FROM runs WHERE run_id = ?"
        )
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(query, [run_id])
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None

    def list_latest_per_serial(self) -> list[RunRecord]:
        """Return the most recent RunRecord for each unique serial_number, naturally
        sorted so '2' < '10' instead of lexicographic '10' < '2'."""
        self.initialize()
        query = (
            "SELECT run_id, serial_number, preamp_version, noise_head_id, station_name, instrument_id, notes, "
            "timestamp_utc, is_retest, previous_run_id, nf_trace_json, gain_trace_json, summary_json, operator, "
            "calibration_date, calibration_method, fixture_loss_db, measurement_bandwidth_hz, key_point_averages, report_path "
            "FROM runs r1 WHERE timestamp_utc = ("
            "  SELECT MAX(timestamp_utc) FROM runs r2 WHERE r2.serial_number = r1.serial_number"
            ")"
        )
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(query)
            records = [self._row_to_record(row) for row in cursor.fetchall()]
        records.sort(key=lambda r: _natural_key(r.serial_number))
        return records

    def list_runs(self, serial_number: str, limit: int | None = None) -> list[RunRecord]:
        self.initialize()
        query = (
            "SELECT run_id, serial_number, preamp_version, noise_head_id, station_name, instrument_id, notes, "
            "timestamp_utc, is_retest, previous_run_id, nf_trace_json, gain_trace_json, summary_json, operator, "
            "calibration_date, calibration_method, fixture_loss_db, measurement_bandwidth_hz, key_point_averages, report_path "
            "FROM runs WHERE serial_number = ? ORDER BY timestamp_utc DESC"
        )
        parameters: list[object] = [serial_number]
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(query, parameters)
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def _row_to_record(self, row: tuple[object, ...]) -> RunRecord:
        return RunRecord(
            run_id=str(row[0]),
            serial_number=str(row[1]),
            preamp_version=str(row[2]),
            noise_head_id=str(row[3]),
            station_name=str(row[4]),
            instrument_id=str(row[5]),
            notes=str(row[6]),
            timestamp_utc=datetime.fromisoformat(str(row[7])),
            is_retest=bool(row[8]),
            previous_run_id=str(row[9]) if row[9] else None,
            nf_trace=SweepTrace.from_dict(json.loads(str(row[10]))),
            gain_trace=SweepTrace.from_dict(json.loads(str(row[11]))),
            summary=MeasurementSummary.from_dict(json.loads(str(row[12]))),
            operator=str(row[13]) if len(row) > 13 else "",
            calibration_date=str(row[14]) if len(row) > 14 else "",
            calibration_method=str(row[15]) if len(row) > 15 else "",
            fixture_loss_db=float(row[16]) if len(row) > 16 else 0.0,
            measurement_bandwidth_hz=float(row[17]) if len(row) > 17 and row[17] is not None else 0.0,
            key_point_averages=int(row[18]) if len(row) > 18 and row[18] is not None else 0,
            report_path=str(row[19]) if len(row) > 19 and row[19] else None,
        )
