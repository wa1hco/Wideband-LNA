from __future__ import annotations

import io
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from lna_bench import cli


@dataclass(slots=True)
class CommandResult:
    code: int
    stdout: str
    stderr: str


def _run_cli(args: list[str]) -> CommandResult:
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    exit_code = 0

    with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
        try:
            result = cli.main(args)
            exit_code = int(result) if result is not None else 0
        except SystemExit as exc:
            exit_code = int(exc.code) if isinstance(exc.code, int) else 1
        except Exception:
            traceback.print_exc(file=stderr_buffer)
            exit_code = 1

    return CommandResult(code=exit_code, stdout=stdout_buffer.getvalue(), stderr=stderr_buffer.getvalue())


def _prefix_args(config_path: str, mock_mode: bool) -> list[str]:
    args = ["--config", config_path]
    if mock_mode:
        args.append("--mock")
    return args


def _display_result(title: str, result: CommandResult) -> None:
    if result.code == 0:
        st.success(f"{title} succeeded")
    else:
        st.error(f"{title} failed (exit code {result.code})")

    if result.stdout.strip():
        st.text_area(f"{title} output", result.stdout, height=220)
    if result.stderr.strip():
        st.text_area(f"{title} errors", result.stderr, height=180)


def _extract_report_path(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if line.startswith("Report:"):
            return line.split("Report:", 1)[1].strip()
    return None


def render_app() -> None:
    st.set_page_config(page_title="LNA Bench GUI", page_icon="RF", layout="wide")
    st.title("LNA Bench")
    st.caption("Streamlit front end for lna-bench commands")

    with st.sidebar:
        st.header("Session")
        config_path = st.text_input("Config path", value="config/station.toml")
        mock_mode = st.checkbox("Mock mode (no instrument)", value=True)
        st.caption("Use mock mode for offline report and workflow testing.")

    base_args = _prefix_args(config_path=config_path, mock_mode=mock_mode)

    st.subheader("Preflight")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Ready", use_container_width=True):
            result = _run_cli(base_args + ["ready"])
            _display_result("ready", result)
    with c2:
        if st.button("Probe", use_container_width=True):
            result = _run_cli(base_args + ["probe"])
            _display_result("probe", result)
    with c3:
        if st.button("Verify Config", use_container_width=True):
            result = _run_cli(base_args + ["verify-config"])
            _display_result("verify-config", result)

    st.divider()
    st.subheader("Record Run")
    r1, r2, r3 = st.columns(3)
    with r1:
        serial = st.text_input("Serial", value="SN001")
    with r2:
        preamp_version = st.text_input("Preamp Version", value="REV-A")
    with r3:
        noise_head_id = st.text_input("Noise Head ID", value="NH-SIM")

    r4, r5 = st.columns(2)
    with r4:
        operator = st.text_input("Operator", value="")
    with r5:
        is_retest = st.checkbox("Retest")

    notes = st.text_area("Notes", value="")

    if st.button("Record", use_container_width=True):
        cmd = base_args + [
            "record",
            "--serial",
            serial.strip(),
            "--preamp-version",
            preamp_version.strip(),
            "--noise-head-id",
            noise_head_id.strip(),
            "--operator",
            operator.strip(),
            "--notes",
            notes,
        ]
        if is_retest:
            cmd.append("--retest")

        result = _run_cli(cmd)
        _display_result("record", result)
        report_path = _extract_report_path(result.stdout)
        if report_path:
            st.info(f"Report file: {report_path}")

    st.divider()
    st.subheader("History And Report")
    h1, h2 = st.columns(2)
    with h1:
        history_serial = st.text_input("History serial", value="SN001")
        if st.button("Show History", use_container_width=True):
            result = _run_cli(base_args + ["history", "--serial", history_serial.strip()])
            _display_result("history", result)

    with h2:
        regen_serial = st.text_input("Regenerate report serial", value="SN001")
        regen_all = st.checkbox("Regenerate all runs for serial")
        if st.button("Regenerate Report", use_container_width=True):
            cmd = base_args + ["regen-report", "--serial", regen_serial.strip()]
            if regen_all:
                cmd.append("--all")
            result = _run_cli(cmd)
            _display_result("regen-report", result)

    st.divider()
    st.subheader("Open Report Folder")
    if st.button("Show latest reports path"):
        reports_dir = Path("reports") / "reports"
        st.code(str(reports_dir.resolve()))


def launch() -> None:
    """Entry point for the lna-bench-gui console script."""
    from streamlit.web import cli as streamlit_cli

    script_path = Path(__file__).resolve()
    sys.argv = ["streamlit", "run", str(script_path)]
    streamlit_cli.main()


# When Streamlit re-executes this file as the app script, __name__ == "__main__".
# Call render_app() directly rather than launch() to avoid recursive server start.
render_app()
