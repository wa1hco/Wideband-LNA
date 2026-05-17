from __future__ import annotations

import argparse
from contextlib import nullcontext
from pathlib import Path

from lna_bench.config import AppConfig, load_config
from lna_bench.instruments.n8973a import N8973AController
from lna_bench.models import MeasurementSummary, RunRecord
from lna_bench.process_guard import process_guard
from lna_bench.reporting import HtmlReportGenerator, JsonArtifactWriter
from lna_bench.storage import RunRepository
from lna_bench.transport import MockTransport, VisaResourceSettings, VisaTransport


def _get_doc_dir() -> Path | None:
    """Return the path to the doc directory (test/lna_bench/doc)."""
    project_root = Path(__file__).parent.parent.parent.parent.parent
    doc_dir = project_root / "doc"
    return doc_dir if doc_dir.exists() else None

def _build_transport(config: AppConfig, mock: bool = False) -> "VisaTransport | MockTransport":
    if mock:
        return MockTransport(
            start_hz=config.sweep.start_hz,
            stop_hz=config.sweep.stop_hz,
            points=config.sweep.points,
        )
    settings = VisaResourceSettings(
        resource_name=config.visa.resource_name,
        backend=config.visa.backend,
        timeout_ms=config.visa.timeout_ms,
        read_termination=config.visa.read_termination,
        write_termination=config.visa.write_termination,
    )
    return VisaTransport(settings)


def _build_controller(config: AppConfig, transport: VisaTransport) -> N8973AController:
    return N8973AController(
        transport=transport,
        sweep=config.sweep,
        commands=config.commands,
        control=config.control,
        configuration=config.configuration,
    )


def _instrument_command_guard(config: AppConfig):
    if not config.runtime.single_instance:
        return nullcontext()
    lock_path = config.station.output_dir / ".locks" / "instrument.lock"
    return process_guard(lock_path=lock_path, stale_seconds=config.runtime.lock_stale_seconds)


def _nearest_value(frequencies_hz: list[float], values: list[float], target_hz: float) -> float:
    best_index = min(range(len(frequencies_hz)), key=lambda idx: abs(frequencies_hz[idx] - target_hz))
    return values[best_index]


def _build_summary_with_key_frequencies(record: RunRecord, key_frequencies_hz: list[float]) -> MeasurementSummary:
    key_points: dict[str, dict[str, float]] = {}
    for target_hz in key_frequencies_hz:
        key = f"{target_hz / 1_000_000_000:.3f} GHz"
        key_points[key] = {
            "nf_db": _nearest_value(record.nf_trace.frequencies_hz, record.nf_trace.values, target_hz),
            "gain_db": _nearest_value(record.gain_trace.frequencies_hz, record.gain_trace.values, target_hz),
        }

    return MeasurementSummary(
        nf_min_db=min(record.nf_trace.values),
        nf_max_db=max(record.nf_trace.values),
        nf_avg_db=sum(record.nf_trace.values) / len(record.nf_trace.values),
        gain_min_db=min(record.gain_trace.values),
        gain_max_db=max(record.gain_trace.values),
        gain_avg_db=sum(record.gain_trace.values) / len(record.gain_trace.values),
        key_points=key_points,
    )


def _cmd_probe(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    transport = _build_transport(config, mock=getattr(args, "mock", False))
    controller = _build_controller(config, transport)
    with _instrument_command_guard(config):
        with transport:
            controller.acquire_computer_control()
            try:
                print(f"Resources: {transport.list_resources()}")
                print(f"Instrument ID: {controller.identify()}")
            finally:
                controller.release_to_user_control()
    return 0


def _cmd_verify_config(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    transport = _build_transport(config, mock=getattr(args, "mock", False))
    controller = _build_controller(config, transport)

    with _instrument_command_guard(config):
        with transport:
            controller.acquire_computer_control()
            try:
                controller.apply_configuration()
                results = controller.verify_configuration()
            finally:
                controller.release_to_user_control()

    if not results:
        print("No configuration checks defined (configuration.verify_checks is empty).")
        return 0

    failed = 0
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        expected = result.expected if result.expected is not None else "<none>"
        print(
            f"[{status}] {result.name}: query={result.query!r} response={result.response!r} expected={expected!r}"
        )
        if not result.passed:
            failed += 1

    if failed and controller.should_fail_on_configuration_mismatch():
        return 2
    return 0


def _cmd_init_db(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    repository = RunRepository(config.station.database_path)
    repository.initialize()
    print(f"Initialized database at {config.station.database_path}")
    return 0


def _cmd_regen_report(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    repository = RunRepository(config.station.database_path)

    if args.run_id:
        run = repository.get_run_by_id(args.run_id)
        if run is None:
            raise SystemExit(f"Run ID not found: {args.run_id}")
        runs = [run]
    else:
        runs = repository.list_runs(args.serial)
        if not runs:
            raise SystemExit(f"No runs found for serial {args.serial}")
        if not args.all:
            runs = runs[:1]  # latest only

    doc_dir = _get_doc_dir()
    report_generator = HtmlReportGenerator(config.station.output_dir, doc_dir=doc_dir)
    for run in runs:
        run.summary = _build_summary_with_key_frequencies(run, config.sweep.key_frequencies_hz)
        previous = repository.get_run_by_id(run.previous_run_id) if run.previous_run_id else None
        report_path = report_generator.write_report(run, previous_record=previous)
        repository.update_report_path(run.run_id, str(report_path))
        print(f"Report: {report_path}")
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    repository = RunRepository(config.station.database_path)
    rows = repository.list_runs(args.serial)
    if not rows:
        print(f"No runs found for {args.serial}")
        return 0

    for row in rows:
        report = row.report_path or "<no report>"
        print(
            f"{row.timestamp_utc.isoformat()}  run_id={row.run_id}  retest={row.is_retest}  "
            f"notes={row.notes!r}  report={report}"
        )
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.retest and not args.notes.strip():
        raise SystemExit("Retests require non-empty --notes describing what changed")

    repository = RunRepository(config.station.database_path)
    repository.initialize()
    previous_run = repository.get_latest_run(args.serial)
    previous_run_id = previous_run.run_id if previous_run is not None else None

    transport = _build_transport(config, mock=getattr(args, "mock", False))
    controller = _build_controller(config, transport)

    with _instrument_command_guard(config):
        with transport:
            controller.acquire_computer_control()
            try:
                controller.apply_configuration()
                verification = controller.verify_configuration()
                failed_checks = [item for item in verification if not item.passed]
                if failed_checks and controller.should_fail_on_configuration_mismatch():
                    failure_names = ", ".join(item.name for item in failed_checks)
                    raise SystemExit(f"Instrument configuration verification failed: {failure_names}")

                instrument_id = controller.identify()
                capture = controller.capture_sweep()
            finally:
                controller.release_to_user_control()

    record = RunRecord.create(
        serial_number=args.serial,
        preamp_version=args.preamp_version,
        noise_head_id=args.noise_head_id,
        station_name=config.station.name,
        instrument_id=instrument_id,
        notes=args.notes,
        is_retest=args.retest or previous_run is not None,
        previous_run_id=previous_run_id,
        nf_trace=capture.nf_trace,
        gain_trace=capture.gain_trace,
        summary=capture.summary,
        operator=getattr(args, "operator", ""),
        calibration_date=config.calibration.calibration_date,
        calibration_method=config.calibration.calibration_method,
        fixture_loss_db=config.calibration.fixture_loss_db,
    )
    repository.save_run(record)

    artifact_writer = JsonArtifactWriter(config.station.output_dir)
    data_path = artifact_writer.write_run_data(record)
    doc_dir = _get_doc_dir()
    report_generator = HtmlReportGenerator(config.station.output_dir, doc_dir=doc_dir)
    report_path = report_generator.write_report(record, previous_record=previous_run)
    repository.update_report_path(record.run_id, str(report_path))

    print(f"Saved run {record.run_id} for serial {record.serial_number}")
    print(f"Data: {data_path}")
    print(f"Report: {report_path}")
    return 0


def _cmd_ready(args: argparse.Namespace) -> int:
    """Preflight check: GPIB connected, instrument reachable, calibration valid, config checks pass."""
    config = load_config(args.config)
    checks_passed = 0
    checks_failed = 0

    print("\n=== PREFLIGHT READY CHECK ===")
    print(f"Station: {config.station.name}")
    print(f"Output: {config.station.output_dir}")
    print(f"Database: {config.station.database_path}")

    # Check 1: GPIB and instrument reachability
    print("\n[1/3] Probing VISA resource...")
    transport = _build_transport(config, mock=args.mock)
    controller = _build_controller(config, transport)
    try:
        with _instrument_command_guard(config):
            with transport:
                controller.acquire_computer_control()
                try:
                    instrument_id = controller.identify()
                    print(f"  OK Instrument: {instrument_id}")
                    checks_passed += 1
                finally:
                    controller.release_to_user_control()
    except Exception as e:
        print(f"  FAIL GPIB probe failed: {e}")
        checks_failed += 1

    # Check 2: Configuration verification
    print("\n[2/3] Verifying instrument configuration...")
    transport2 = _build_transport(config, mock=args.mock)
    controller2 = _build_controller(config, transport2)
    try:
        with _instrument_command_guard(config):
            with transport2:
                controller2.acquire_computer_control()
                try:
                    controller2.apply_configuration()
                    results = controller2.verify_configuration()
                    failed = [r for r in results if not r.passed]
                    if failed:
                        print("  FAIL Configuration check(s) failed:")
                        for result in failed:
                            print(f"    - {result.name}: expected {result.expected!r}, got {result.response!r}")
                        checks_failed += 1
                    else:
                        print(f"  OK All configuration checks passed ({len(results)} checks)")
                        checks_passed += 1
                finally:
                    controller2.release_to_user_control()
    except Exception as e:
        print(f"  FAIL Configuration verification failed: {e}")
        checks_failed += 1

    # Check 3: Calibration metadata
    print("\n[3/3] Calibration status...")
    if config.calibration.calibration_date:
        print(f"  OK Calibration: {config.calibration.calibration_date}")
        print(f"    Method: {config.calibration.calibration_method}")
        print(f"    Fixture loss: {config.calibration.fixture_loss_db} dB")
        checks_passed += 1
    else:
        print("  WARN Calibration date not set in config")
        checks_failed += 1

    print(f"\n=== SUMMARY: {checks_passed}/3 passed ===")
    if checks_failed == 0:
        print("Station is ready for testing.")
        return 0
    else:
        print("Fix issues above before proceeding.")
        return 1


def _cmd_next_dut(args: argparse.Namespace) -> int:
    """Convenience command: shows next unit info."""
    print("\n=== NEXT DUT ===")
    print("Station is ready for the next unit.")
    print("Use: lna-bench --config config/station.toml record --serial SN_XXX ...")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lna-bench", description="LNA characterization bench tools")
    parser.add_argument("--config", default="config/station.toml", help="Path to station TOML config")
    parser.add_argument("--mock", action="store_true", help="Use synthetic data instead of real GPIB instrument (no GPIB required)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe", help="Probe the VISA resource and print the instrument identity")
    probe.set_defaults(func=_cmd_probe)

    verify_config = subparsers.add_parser(
        "verify-config",
        help="Apply and verify instrument configuration, then return to user control",
    )
    verify_config.set_defaults(func=_cmd_verify_config)

    init_db = subparsers.add_parser("init-db", help="Initialize the local run-history database")
    init_db.set_defaults(func=_cmd_init_db)

    history = subparsers.add_parser("history", help="List historical runs for a serial number")
    history.add_argument("--serial", required=True, help="Serial number to query")
    history.set_defaults(func=_cmd_history)

    record = subparsers.add_parser("record", help="Acquire and persist one characterization run")
    record.add_argument("--serial", required=True, help="DUT serial number")
    record.add_argument("--preamp-version", required=True, help="Preamp revision or build variant")
    record.add_argument("--noise-head-id", required=True, help="Noise head identifier")
    record.add_argument("--operator", default="", help="Operator name (optional)")
    record.add_argument("--notes", required=True, help="Notes for the run or retest")
    record.add_argument("--retest", action="store_true", help="Mark this run as a retest")
    record.set_defaults(func=_cmd_record)

    regen = subparsers.add_parser("regen-report", help="Re-generate HTML report(s) from stored run data")
    regen_group = regen.add_mutually_exclusive_group(required=True)
    regen_group.add_argument("--run-id", help="Specific run ID to regenerate")
    regen_group.add_argument("--serial", help="Serial number (regenerates latest run, or all with --all)")
    regen.add_argument("--all", action="store_true", help="Regenerate all runs for the serial number")
    regen.set_defaults(func=_cmd_regen_report)

    ready = subparsers.add_parser("ready", help="Run preflight checks (GPIB, config, calibration)")
    ready.set_defaults(func=_cmd_ready)

    next_dut = subparsers.add_parser("next-dut", help="Show next unit template (batch mode helper)")
    next_dut.set_defaults(func=_cmd_next_dut)

    return parser

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
