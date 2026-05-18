# LNA Characterization Bench

Initial implementation for a Windows bench application that characterizes low-noise amplifiers with an N8973A through a PyVISA-compatible Xyphro GPIB interface.

Current scope:

- PyVISA transport abstraction
- N8973A instrument wrapper with configurable SCPI queries
- SQLite-backed run history for repeated tests of the same serial number
- HTML report generation with swept NF and gain plots
- CLI workflow for instrument probe and run capture

## Layout

- `src/lna_bench/transport.py`: VISA transport wrapper
- `src/lna_bench/instruments/n8973a.py`: measurement acquisition and summary generation
- `src/lna_bench/storage.py`: SQLite persistence and history lookup
- `src/lna_bench/reporting.py`: HTML report output with inline SVG plots
- `src/lna_bench/cli.py`: command-line entry points
- `config/station.example.toml`: example station configuration

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## Configure

Copy `config/station.example.toml` to `config/station.toml` and adjust the VISA resource and SCPI commands for your N8973A setup.

## Commands

Note: `--config` is a global option and must appear before the subcommand.

Probe the instrument connection:

```powershell
lna-bench --config config/station.toml probe
```

Capture and store a new run:

```powershell
lna-bench --config config/station.toml record --serial SN123 --preamp-version REV-A --noise-head-id NH-01 --notes "Initial baseline"
```

Capture a retest with notes describing the change:

```powershell
lna-bench --config config/station.toml record --serial SN123 --preamp-version REV-A --noise-head-id NH-01 --retest --notes "Replaced input matching capacitor C14 with 0.8 pF"
```

List prior runs for a serial number:

```powershell
lna-bench --config config/station.toml history --serial SN123
```

## Streamlit GUI

The project includes a Streamlit front end for day-to-day bench operation.

Install dependencies and launch:

```powershell
pip install -e .
lna-bench-gui
```

Or launch directly with Streamlit:

```powershell
streamlit run src/lna_bench/gui_streamlit.py
```

The GUI exposes:

- `ready`, `probe`, and `verify-config`
- `record` form (serial, preamp version, noise head ID, operator, notes)
- `history` and `regen-report`
- a `Mock mode` toggle for offline operation

## Batch Workflow (25 LNA)

Recommended preparation before a 25-unit run:

1. Verify instrument reachability:

```powershell
lna-bench --config config/station.toml probe
```

2. Verify bench configuration checks:

```powershell
lna-bench --config config/station.toml verify-config
```

3. Initialize database once (safe to rerun):

```powershell
lna-bench --config config/station.toml init-db
```

4. Run all units from a serial list file (one serial per line in `serials.txt`):

```powershell
$serials = Get-Content .\serials.txt | Where-Object { $_.Trim() -ne "" }
foreach ($sn in $serials) {
	lna-bench --config config/station.toml record --serial $sn --preamp-version REV-A --noise-head-id NH-01 --notes "Batch run 2026-05-16"
}
```

5. Check history for any unit:

```powershell
lna-bench --config config/station.toml history --serial SN001
```

6. Regenerate latest report for a serial number if needed:

```powershell
lna-bench --config config/station.toml regen-report --serial SN001
```

## Notes

The N8973A command set can vary depending on how the instrument is configured. The SCPI used here is intentionally driven by configuration so the bench can be adapted without rewriting the application.
