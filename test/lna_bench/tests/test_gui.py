"""Test GUI helper functions and CLI integration in mock mode.

These tests exercise gui_streamlit._run_cli() without launching a browser.
Streamlit must be installed but does not need a running server.
"""
from __future__ import annotations

import pytest

# Import only the helpers that don't touch Streamlit widgets
from lna_bench.gui_streamlit import (
    _extract_report_path,
    _prefix_args,
    _run_cli,
)

CONFIG = "config/station.example.toml"


# ---------------------------------------------------------------------------
# Pure helper tests (no subprocess, no hardware)
# ---------------------------------------------------------------------------

class TestPrefixArgs:
    def test_mock_flag_present(self):
        args = _prefix_args(CONFIG, mock_mode=True)
        assert "--mock" in args

    def test_mock_flag_absent(self):
        args = _prefix_args(CONFIG, mock_mode=False)
        assert "--mock" not in args

    def test_config_present(self):
        args = _prefix_args(CONFIG, mock_mode=True)
        assert "--config" in args
        assert CONFIG in args


class TestExtractReportPath:
    def test_extracts_path(self):
        stdout = "some output\nReport: /tmp/reports/SN001/run_001.html\ndone\n"
        assert _extract_report_path(stdout) == "/tmp/reports/SN001/run_001.html"

    def test_returns_none_when_absent(self):
        assert _extract_report_path("no report line here\n") is None

    def test_strips_whitespace(self):
        result = _extract_report_path("Report:   /a/b/c.html   \n")
        assert result == "/a/b/c.html"


# ---------------------------------------------------------------------------
# Integration: _run_cli in mock mode (no instrument required)
# ---------------------------------------------------------------------------

class TestRunCliMock:
    def test_probe_exits_zero(self):
        result = _run_cli(["--mock", "--config", CONFIG, "probe"])
        assert result.code == 0, f"stderr: {result.stderr}"

    def test_probe_returns_idn(self):
        result = _run_cli(["--mock", "--config", CONFIG, "probe"])
        assert "MOCK" in result.stdout or "N8973A" in result.stdout

    def test_record_exits_zero(self):
        result = _run_cli([
            "--mock", "--config", CONFIG,
            "record",
            "--serial", "SN-GUI-TEST",
            "--preamp-version", "REV-A",
            "--noise-head-id", "NH-SIM",
            "--operator", "pytest",
        ])
        assert result.code == 0, f"stderr: {result.stderr}"

    def test_record_produces_report_path(self):
        result = _run_cli([
            "--mock", "--config", CONFIG,
            "record",
            "--serial", "SN-GUI-TEST",
            "--preamp-version", "REV-A",
            "--noise-head-id", "NH-SIM",
        ])
        path = _extract_report_path(result.stdout)
        assert path is not None, f"No 'Report:' line in stdout:\n{result.stdout}"

    def test_ready_exits_zero_in_mock(self):
        result = _run_cli(["--mock", "--config", CONFIG, "ready"])
        assert result.code == 0, f"stderr: {result.stderr}"

    def test_bad_subcommand_exits_nonzero(self):
        result = _run_cli(["--mock", "--config", CONFIG, "not-a-command"])
        assert result.code != 0
