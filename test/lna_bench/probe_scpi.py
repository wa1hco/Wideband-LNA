#!/usr/bin/env python3
"""
probe_scpi.py — Interactive SCPI troubleshooting tool for the N8973A NFA.

Usage:
    python probe_scpi.py [--resource VISA_RESOURCE] [--backend VISA_BACKEND]
    python probe_scpi.py --config path/to/station.toml

Without arguments, lists all VISA resources and exits.

In interactive mode, type any SCPI command or query.  Queries (ending with '?')
are read back automatically.  Special built-in commands:

    list        — list all VISA resources on the bus
    idn         — send *IDN? and print result
    init        — query INIT:CONT?, set INIT:CONT ON, re-query to verify
    nf          — fetch FETC:CORR:NFIG? (first 5 values only)
    gain        — fetch FETC:CORR:GAIN? (first 5 values only)
    quit / exit — close and exit
"""
from __future__ import annotations

import argparse
import sys
import textwrap

try:
    import pyvisa
except ImportError:
    print("pyvisa is not installed. Run: pip install pyvisa pyvisa-py")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_rm(backend: str | None = None) -> pyvisa.ResourceManager:
    if backend:
        return pyvisa.ResourceManager(backend)
    return pyvisa.ResourceManager()


def _list_resources(rm: pyvisa.ResourceManager) -> None:
    resources = rm.list_resources()
    if not resources:
        print("No VISA resources found.")
    else:
        print(f"Found {len(resources)} resource(s):")
        for r in resources:
            print(f"  {r}")


def _open_instrument(rm: pyvisa.ResourceManager, resource: str, timeout_ms: int = 300_000):
    inst = rm.open_resource(resource)
    inst.timeout = timeout_ms
    inst.read_termination = "\n"
    inst.write_termination = "\n"
    return inst


def _query(inst, cmd: str) -> str:
    return inst.query(cmd).strip()


def _write(inst, cmd: str) -> None:
    inst.write(cmd)


def _preview_csv(raw: str, n: int = 5) -> str:
    """Return first n comma-separated values with a count suffix."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    preview = ", ".join(parts[:n])
    if len(parts) > n:
        preview += f"  … ({len(parts)} total)"
    return preview


# ---------------------------------------------------------------------------
# Built-in macro handlers
# ---------------------------------------------------------------------------

BUILTINS = {}


def builtin(name: str):
    def decorator(fn):
        BUILTINS[name] = fn
        return fn
    return decorator


@builtin("list")
def _do_list(inst, rm):
    _list_resources(rm)


@builtin("idn")
def _do_idn(inst, rm):
    resp = _query(inst, "*IDN?")
    print(f"  IDN: {resp}")


@builtin("init")
def _do_init(inst, rm):
    before = _query(inst, "INIT:CONT?")
    print(f"  INIT:CONT? before: {before}")
    _write(inst, "INIT:CONT ON")
    after = _query(inst, "INIT:CONT?")
    print(f"  INIT:CONT? after:  {after}")
    if after.strip() == "1":
        print("  OK — continuous sweep is enabled")
    else:
        print(f"  WARNING — unexpected response: {after!r}")


@builtin("nf")
def _do_nf(inst, rm):
    raw = _query(inst, "FETC:CORR:NFIG?")
    print(f"  NF (dB): {_preview_csv(raw)}")


@builtin("gain")
def _do_gain(inst, rm):
    raw = _query(inst, "FETC:CORR:GAIN?")
    print(f"  Gain (dB): {_preview_csv(raw)}")


# ---------------------------------------------------------------------------
# Config loading (optional)
# ---------------------------------------------------------------------------

def _load_resource_from_config(config_path: str) -> tuple[str, str | None, int]:
    """Return (resource_name, backend, timeout_ms) from a station.toml."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    from pathlib import Path

    with open(config_path, "rb") as fh:
        raw = tomllib.load(fh)
    visa = raw.get("visa", {})
    resource = visa.get("resource_name", "")
    backend = str(visa.get("backend", "")).strip() or None
    timeout_ms = int(visa.get("timeout_ms", 300_000))
    return resource, backend, timeout_ms


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def _repl(inst, rm):
    print(textwrap.dedent("""
        SCPI probe — connected.
        Queries (ending '?') are read automatically.
        Built-ins: list  idn  init  nf  gain  quit
    """).strip())
    while True:
        try:
            line = input("scpi> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        cmd = line.lower()
        if cmd in ("quit", "exit", "q"):
            break

        if cmd in BUILTINS:
            try:
                BUILTINS[cmd](inst, rm)
            except Exception as exc:
                print(f"  ERROR: {exc}")
            continue

        # Raw SCPI
        try:
            if line.endswith("?"):
                resp = _query(inst, line)
                print(f"  {resp}")
            else:
                _write(inst, line)
                print("  OK")
        except Exception as exc:
            print(f"  ERROR: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--resource", "-r", help="VISA resource string (e.g. GPIB0::28::INSTR)")
    parser.add_argument("--backend", "-b", default="", help="PyVISA backend (blank = auto)")
    parser.add_argument("--timeout-ms", type=int, default=300_000, help="VISA timeout in ms")
    parser.add_argument("--config", "-c", help="Path to station.toml (overrides --resource/--backend)")
    args = parser.parse_args()

    resource: str | None = args.resource
    backend: str | None = args.backend.strip() or None
    timeout_ms: int = args.timeout_ms

    if args.config:
        resource, backend, timeout_ms = _load_resource_from_config(args.config)
        print(f"Loaded resource from config: {resource}")

    rm = _open_rm(backend)

    if not resource:
        _list_resources(rm)
        rm.close()
        return

    print(f"Connecting to {resource} …")
    try:
        inst = _open_instrument(rm, resource, timeout_ms)
    except Exception as exc:
        print(f"Failed to open resource: {exc}")
        rm.close()
        sys.exit(1)

    try:
        # Always print IDN on connect
        try:
            idn = _query(inst, "*IDN?")
            print(f"Connected: {idn}")
        except Exception as exc:
            print(f"Warning — *IDN? failed: {exc}")

        _repl(inst, rm)
    finally:
        try:
            inst.close()
        except Exception:
            pass
        rm.close()
        print("Disconnected.")


if __name__ == "__main__":
    main()
