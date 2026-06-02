from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import streamlit as st

from lna_bench.config import AppConfig, load_config
from lna_bench.instruments.n8973a import N8973AController
from lna_bench.models import RunRecord
from lna_bench.reporting import JsonArtifactWriter
from lna_bench.reporting_compact import CompactHtmlReportGenerator, render_summary_matrix
from lna_bench.storage import RunRepository
from lna_bench.transport import VisaResourceSettings, VisaTransport


def _build_transport(config: AppConfig) -> VisaTransport:
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


def _do_probe(config: AppConfig) -> tuple[bool, str]:
    transport = _build_transport(config)
    controller = _build_controller(config, transport)
    with transport:
        controller.acquire_computer_control()
        snapshot = controller.snapshot_state()
        try:
            resources = transport.list_resources()
            instrument_id = controller.identify()
        finally:
            controller.restore_state(snapshot)
            controller.release_to_user_control()
    return True, f"Probe OK. Instrument: {instrument_id}; Resources: {resources}"


def _do_ready(config: AppConfig) -> tuple[bool, str]:
    transport = _build_transport(config)
    controller = _build_controller(config, transport)
    with transport:
        controller.acquire_computer_control()
        snapshot = controller.snapshot_state()
        try:
            controller.apply_configuration()
            results = controller.verify_configuration()
            failed = [item for item in results if not item.passed]
        finally:
            controller.restore_state(snapshot)
            controller.release_to_user_control()

    if failed and controller.should_fail_on_configuration_mismatch():
        names = ", ".join(item.name for item in failed)
        return False, f"Ready check failed: {names}"
    return True, "Ready check passed."


def _do_record(
    config: AppConfig,
    *,
    serial: str,
    preamp_version: str,
    operator: str,
    noise_head_id: str,
    notes: str,
    force_retest: bool,
) -> tuple[bool, str, str | None]:
    if not serial.strip():
        return False, "Serial is required.", None
    if not preamp_version.strip():
        return False, "Preamp Version is required.", None
    if not noise_head_id.strip():
        return False, "Noise head ID is required.", None
    if force_retest and not notes.strip():
        return False, "Retests require non-empty notes.", None

    repository = RunRepository(config.station.database_path)
    repository.initialize()
    previous_run = repository.get_latest_run(serial)
    previous_run_id = previous_run.run_id if previous_run is not None else None

    transport = _build_transport(config)
    controller = _build_controller(config, transport)

    with transport:
        controller.acquire_computer_control()
        snapshot = controller.snapshot_state()
        try:
            controller.apply_configuration()
            verification = controller.verify_configuration()
            failed_checks = [item for item in verification if not item.passed]
            if failed_checks and controller.should_fail_on_configuration_mismatch():
                failure_names = ", ".join(item.name for item in failed_checks)
                return False, f"Configuration verification failed: {failure_names}", None

            instrument_id = controller.identify()
            capture = controller.capture_sweep()
        finally:
            controller.restore_state(snapshot)
            controller.release_to_user_control()

    record = RunRecord.create(
        serial_number=serial.strip(),
        preamp_version=preamp_version.strip(),
        operator=operator.strip(),
        noise_head_id=noise_head_id.strip(),
        station_name=config.station.name,
        instrument_id=instrument_id,
        notes=notes,
        is_retest=force_retest or previous_run is not None,
        previous_run_id=previous_run_id,
        nf_trace=capture.nf_trace,
        gain_trace=capture.gain_trace,
        summary=capture.summary,
        measurement_bandwidth_hz=capture.measurement_bandwidth_hz,
        key_point_averages=capture.key_point_averages,
    )
    repository.save_run(record)

    artifact_writer = JsonArtifactWriter(config.station.output_dir)
    data_path = artifact_writer.write_run_data(record)
    doc_dir = Path(__file__).resolve().parent.parent.parent / "doc"
    report_generator = CompactHtmlReportGenerator(
        config.station.output_dir,
        doc_dir=doc_dir if doc_dir.exists() else None,
    )
    report_path = report_generator.write_report(record, previous_record=previous_run)
    repository.update_report_path(record.run_id, str(report_path))
    return True, f"Recorded run {record.run_id}", str(report_path)


def _do_print_all(config: AppConfig) -> tuple[bool, str, str | None]:
    """Build one combined HTML from the latest run per serial and open it for printing."""
    repository = RunRepository(config.station.database_path)
    repository.initialize()
    records = repository.list_latest_per_serial()
    if not records:
        return False, "No runs in the database yet.", None
    doc_dir = Path(__file__).resolve().parent.parent.parent / "doc"
    generator = CompactHtmlReportGenerator(
        config.station.output_dir,
        doc_dir=doc_dir if doc_dir.exists() else None,
    )
    title = f"LNA Batch — {config.station.name} ({len(records)} units)"
    html = generator.render_combined(records, title=title)
    output_path = Path(config.station.output_dir).resolve() / "reports" / "_combined_latest.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    try:
        webbrowser.open(output_path.as_uri())
    except Exception:
        pass  # path is still in the success message
    return True, f"Combined report ({len(records)} units) → {output_path}", str(output_path)


def _do_print_summary(config: AppConfig) -> tuple[bool, str, str | None]:
    """Build a one-page NF/Gain matrix across all units and open it for printing."""
    repository = RunRepository(config.station.database_path)
    repository.initialize()
    records = repository.list_latest_per_serial()
    if not records:
        return False, "No runs in the database yet.", None
    title = f"LNA Summary — {config.station.name} ({len(records)} units)"
    html = render_summary_matrix(records, title=title)
    output_path = Path(config.station.output_dir).resolve() / "reports" / "_summary_matrix.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    try:
        webbrowser.open(output_path.as_uri())
    except Exception:
        pass
    return True, f"Summary matrix ({len(records)} units) → {output_path}", str(output_path)


def render_app() -> None:
    st.set_page_config(page_title="LNA Bench", layout="wide")
    st.title("LNA Bench")

    default_config = Path("test/lna_bench/config/station.toml")
    config_path = st.text_input("Config path", value=str(default_config))

    try:
        config = load_config(config_path)
    except Exception as exc:  # pragma: no cover - runtime-only UI path
        st.error(f"Config load failed: {exc}")
        return

    left, right = st.columns(2)
    with left:
        if st.button("Probe"):
            ok, message = _do_probe(config)
            if ok:
                st.success(message)
            else:
                st.error(message)

    with right:
        if st.button("Ready"):
            ok, message = _do_ready(config)
            if ok:
                st.success(message)
            else:
                st.error(message)

    st.divider()
    st.subheader("Record")

    serial = st.text_input("Serial", value="")
    preamp_version = st.text_input("Preamp Version", value="")
    operator = st.text_input("Operator", value="")
    noise_head_id = st.text_input("Noise Head ID", value="HP346A")
    notes = st.text_area("Notes", value="")
    force_retest = st.checkbox("Force retest", value=False)

    # Intentionally use a normal button here; form submit buttons caused Streamlit constraints.
    if st.button("Record"):
        ok, message, report_path = _do_record(
            config,
            serial=serial,
            preamp_version=preamp_version,
            operator=operator,
            noise_head_id=noise_head_id,
            notes=notes,
            force_retest=force_retest,
        )
        if ok:
            st.success(message)
            if report_path:
                st.write(f"Report: {report_path}")
        else:
            st.error(message)

    st.divider()
    st.subheader("Batch")
    st.caption("Builds one HTML with the latest run per serial. Ctrl+P in the browser prints them all.")
    batch_left, batch_right = st.columns(2)
    with batch_left:
        if st.button("Print all latest reports"):
            ok, message, combined_path = _do_print_all(config)
            if ok:
                st.success(message)
                if combined_path:
                    st.write(f"File: {combined_path}")
            else:
                st.error(message)
    with batch_right:
        if st.button("Print summary matrix"):
            ok, message, summary_path = _do_print_summary(config)
            if ok:
                st.success(message)
                if summary_path:
                    st.write(f"File: {summary_path}")
            else:
                st.error(message)


def launch() -> None:
    """Entry point for the lna-bench-gui console script."""
    from streamlit.web import cli as streamlit_cli

    sys.argv = ["streamlit", "run", str(Path(__file__).resolve())]
    streamlit_cli.main()


# Run app at script load to avoid recursive launch patterns.
render_app()
