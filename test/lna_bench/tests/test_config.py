"""Verify station.example.toml reflects the bench-validated settings."""
from pathlib import Path

import pytest
from lna_bench.config import load_config

EXAMPLE = Path(__file__).parent.parent / "config" / "station.example.toml"


@pytest.fixture(scope="module")
def cfg():
    return load_config(EXAMPLE)


def test_sweep_range(cfg):
    assert cfg.sweep.start_hz == 10e6
    assert cfg.sweep.stop_hz == 3e9
    assert cfg.sweep.points == 401


def test_key_frequencies(cfg):
    assert cfg.sweep.key_frequencies_hz == [
        50e6, 144e6, 222e6, 432e6, 903e6, 1296e6, 2304e6
    ]


def test_visa_timeout(cfg):
    assert cfg.visa.timeout_ms == 300_000


def test_fetc_corr_commands(cfg):
    assert cfg.commands.nf_data_query == "FETC:CORR:NFIG?"
    assert cfg.commands.gain_data_query == "FETC:CORR:GAIN?"


def test_prepare_commands_empty(cfg):
    assert cfg.commands.prepare_measurement_commands == []


def test_opc_query_blank(cfg):
    assert cfg.commands.opc_query == ""


def test_init_cont_applied(cfg):
    assert "INIT:CONT ON" in cfg.configuration.apply_commands


def test_init_cont_verified(cfg):
    check = cfg.configuration.verify_checks[0]
    assert check.query == "INIT:CONT?"
    assert check.expected == "1"
    assert check.match == "exact"
