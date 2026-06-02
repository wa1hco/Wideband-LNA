from __future__ import annotations

import base64
import math
from html import escape
from pathlib import Path

from lna_bench.models import RunRecord


NF_COLOR = "#0f766e"
GAIN_COLOR = "#b45309"


def _parse_key_freq_to_hz(label: str) -> float:
    parts = label.strip().split()
    value = float(parts[0])
    unit = parts[1].upper() if len(parts) > 1 else "HZ"
    return value * {"GHZ": 1e9, "MHZ": 1e6, "KHZ": 1e3, "HZ": 1.0}.get(unit, 1.0)


def _format_marker_label(f_hz: float) -> str:
    mhz = f_hz / 1e6
    if mhz >= 1000:
        return f"{mhz/1000:.2f}G"
    return f"{mhz:.0f}M"


def _is_valid_db(v: float) -> bool:
    """N8973A returns ~9.91e37 as a 'no data' sentinel; reject that and any non-finite value.
    Real LNA NF/Gain values comfortably fit within ±200 dB."""
    if math.isnan(v) or math.isinf(v):
        return False
    return -200.0 <= v <= 200.0


def _pick_step(span: float, target_ticks: int = 5) -> float:
    if span <= 0:
        return 1.0
    raw = span / target_ticks
    mag = 10 ** math.floor(math.log10(raw))
    norm = raw / mag
    if norm < 1.5:
        step = 1
    elif norm < 3.5:
        step = 2
    elif norm < 7.5:
        step = 5
    else:
        step = 10
    return step * mag


def _combined_plot(record: RunRecord) -> str:
    freqs = record.nf_trace.frequencies_hz
    nf_values = record.nf_trace.values
    gain_values = record.gain_trace.values
    if not freqs or len(freqs) != len(nf_values) or len(freqs) != len(gain_values):
        return ""

    # SVG geometry (pt-ish; viewBox is unitless)
    width, height = 720, 220
    ml, mr, mt, mb = 46, 46, 16, 26
    pw = width - ml - mr
    ph = height - mt - mb

    f_min = min(freqs)
    f_max = max(freqs)
    if f_min <= 0:
        f_min = 1.0  # log can't handle 0
    if f_max <= f_min:
        f_max = f_min * 10

    def x(freq_hz: float) -> float:
        if freq_hz <= 0:
            freq_hz = f_min
        return ml + (math.log10(freq_hz) - math.log10(f_min)) / (math.log10(f_max) - math.log10(f_min)) * pw

    # NF axis: fixed 0–5 dB so a bad ENR-edge point at 10 MHz doesn't squash the rest.
    nf_min, nf_max = 0.0, 5.0

    def y_nf(v: float) -> float:
        clamped = max(nf_min, min(nf_max, v))
        return mt + (1 - (clamped - nf_min) / (nf_max - nf_min)) * ph

    # Gain axis: auto-scale with ±2 dB padding, rounded to nice bounds.
    # Filter out sentinel/invalid values before computing bounds — the trace polyline
    # still includes them but they clip to the axis edges visually.
    valid_gain = [v for v in gain_values if _is_valid_db(v)]
    if not valid_gain:
        valid_gain = [20.0]  # fallback so the plot still renders
    g_lo = min(valid_gain)
    g_hi = max(valid_gain)
    if g_hi - g_lo < 4:
        g_mid = (g_hi + g_lo) / 2
        g_lo = g_mid - 2
        g_hi = g_mid + 2
    gain_step = _pick_step(g_hi - g_lo + 4)
    gain_min = math.floor((g_lo - 1) / gain_step) * gain_step
    gain_max = math.ceil((g_hi + 1) / gain_step) * gain_step
    # Defense in depth: if FP precision made the span collapse, force a non-zero range.
    if gain_max - gain_min < gain_step:
        gain_max = gain_min + max(gain_step, 1.0)

    def y_gain(v: float) -> float:
        clamped = max(gain_min, min(gain_max, v))
        return mt + (1 - (clamped - gain_min) / (gain_max - gain_min)) * ph

    parts: list[str] = []
    parts.append(
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="NF and Gain vs frequency">'
    )

    # plot background
    parts.append(
        f'<rect x="{ml}" y="{mt}" width="{pw}" height="{ph}" fill="#fbfbfb" stroke="#cbd5e1" stroke-width="0.5"/>'
    )

    # x gridlines at decades + decade*2/decade*5 ticks
    log_lo = math.floor(math.log10(f_min))
    log_hi = math.ceil(math.log10(f_max))
    for power in range(log_lo, log_hi + 1):
        for mult in (1, 2, 5):
            f = mult * (10 ** power)
            if f < f_min or f > f_max:
                continue
            xp = x(f)
            color = "#e2e8f0" if mult == 1 else "#f1f5f9"
            parts.append(
                f'<line x1="{xp:.1f}" y1="{mt}" x2="{xp:.1f}" y2="{mt+ph}" stroke="{color}" stroke-width="0.5"/>'
            )
            if mult == 1:
                if f >= 1e9:
                    label = f"{f/1e9:g} GHz"
                elif f >= 1e6:
                    label = f"{f/1e6:g} MHz"
                else:
                    label = f"{f/1e3:g} kHz"
                parts.append(
                    f'<text x="{xp:.1f}" y="{height-12:.1f}" font-size="7" fill="#475569" '
                    f'text-anchor="middle">{label}</text>'
                )

    # NF y gridlines + labels (left)
    nf_v = nf_min
    while nf_v <= nf_max + 1e-9:
        yp = y_nf(nf_v)
        parts.append(
            f'<line x1="{ml}" y1="{yp:.1f}" x2="{ml+pw}" y2="{yp:.1f}" stroke="#e2e8f0" stroke-width="0.5"/>'
        )
        parts.append(
            f'<text x="{ml-3:.1f}" y="{yp+2.5:.1f}" font-size="7" fill="{NF_COLOR}" '
            f'text-anchor="end">{nf_v:g}</text>'
        )
        nf_v += 1.0

    # Gain y labels (right)
    g_v = gain_min
    while g_v <= gain_max + 1e-9:
        yp = y_gain(g_v)
        parts.append(
            f'<text x="{ml+pw+3:.1f}" y="{yp+2.5:.1f}" font-size="7" fill="{GAIN_COLOR}" '
            f'text-anchor="start">{g_v:g}</text>'
        )
        g_v += gain_step

    # Key-frequency markers: vertical dashed lines + freq labels above plot
    for key_str in record.summary.key_points:
        try:
            f_hz = _parse_key_freq_to_hz(key_str)
        except (ValueError, IndexError):
            continue
        if not (f_min <= f_hz <= f_max):
            continue
        xp = x(f_hz)
        parts.append(
            f'<line x1="{xp:.1f}" y1="{mt}" x2="{xp:.1f}" y2="{mt+ph}" '
            f'stroke="#64748b" stroke-width="0.5" stroke-dasharray="2,2"/>'
        )
        parts.append(
            f'<text x="{xp:.1f}" y="{mt-4:.1f}" font-size="6.5" fill="#334155" '
            f'text-anchor="middle">{_format_marker_label(f_hz)}</text>'
        )

    # NF trace
    nf_pts = " ".join(f"{x(f):.1f},{y_nf(v):.1f}" for f, v in zip(freqs, nf_values))
    parts.append(f'<polyline points="{nf_pts}" fill="none" stroke="{NF_COLOR}" stroke-width="1.2"/>')

    # Gain trace
    gain_pts = " ".join(f"{x(f):.1f},{y_gain(v):.1f}" for f, v in zip(freqs, gain_values))
    parts.append(f'<polyline points="{gain_pts}" fill="none" stroke="{GAIN_COLOR}" stroke-width="1.2"/>')

    # Precise key-point dots (from direct measurement)
    for key_str, values in record.summary.key_points.items():
        try:
            f_hz = _parse_key_freq_to_hz(key_str)
        except (ValueError, IndexError):
            continue
        if not (f_min <= f_hz <= f_max):
            continue
        xp = x(f_hz)
        nf_v = values.get("nf_db")
        gain_v = values.get("gain_db")
        if nf_v is not None and nf_min <= nf_v <= nf_max:
            parts.append(f'<circle cx="{xp:.1f}" cy="{y_nf(nf_v):.1f}" r="2.2" fill="{NF_COLOR}"/>')
        if gain_v is not None and gain_min <= gain_v <= gain_max:
            parts.append(f'<circle cx="{xp:.1f}" cy="{y_gain(gain_v):.1f}" r="2.2" fill="{GAIN_COLOR}"/>')

    # frame axes
    parts.append(
        f'<line x1="{ml}" y1="{mt+ph}" x2="{ml+pw}" y2="{mt+ph}" stroke="#0f172a" stroke-width="0.8"/>'
    )
    parts.append(
        f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt+ph}" stroke="{NF_COLOR}" stroke-width="0.8"/>'
    )
    parts.append(
        f'<line x1="{ml+pw}" y1="{mt}" x2="{ml+pw}" y2="{mt+ph}" stroke="{GAIN_COLOR}" stroke-width="0.8"/>'
    )

    # axis titles
    parts.append(
        f'<text x="{ml-30:.1f}" y="{mt-4:.1f}" font-size="7" fill="{NF_COLOR}" '
        f'font-weight="600">NF (dB)</text>'
    )
    parts.append(
        f'<text x="{ml+pw-12:.1f}" y="{mt-4:.1f}" font-size="7" fill="{GAIN_COLOR}" '
        f'font-weight="600" text-anchor="start">Gain (dB)</text>'
    )

    parts.append("</svg>")
    return "".join(parts)


def _embed_schematic_image(doc_dir: Path | None) -> str:
    """Return an <img> tag with the base64-embedded schematic, or '' if no image found."""
    if doc_dir is None:
        return ""
    image_path = doc_dir / "schematic.png"
    if not image_path.exists():
        return ""
    payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f'<img src="data:image/png;base64,{payload}" alt="Schematic" />'


def _format_bw(bw_hz: float) -> str:
    if bw_hz <= 0:
        return "n/a"
    if bw_hz >= 1_000_000:
        return f"{bw_hz / 1_000_000:g} MHz"
    return f"{bw_hz / 1_000:g} kHz"


def _format_sweep_span(record: RunRecord) -> str:
    freqs = record.nf_trace.frequencies_hz
    if not freqs:
        return "n/a"
    start_mhz = min(freqs) / 1_000_000
    stop_mhz = max(freqs) / 1_000_000
    if stop_mhz >= 1_000:
        return f"{start_mhz/1_000:.2f}–{stop_mhz/1_000:.2f} GHz × {len(freqs)} pts"
    return f"{start_mhz:.0f}–{stop_mhz:.0f} MHz × {len(freqs)} pts"


_REPORT_CSS = """
@page { size: letter; margin: 0.5in; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0;
  font-family: "Segoe UI", Tahoma, Arial, sans-serif;
  font-size: 9pt; line-height: 1.25;
  color: #0f172a; background: white;
}
h1 { font-size: 13pt; margin: 0 0 2pt 0; }
h2 {
  font-size: 8.5pt; margin: 6pt 0 2pt 0;
  color: #475569; text-transform: uppercase; letter-spacing: 0.08em;
  border-bottom: 0.5pt solid #cbd5e1; padding-bottom: 1pt;
}
.subtitle { color: #64748b; font-size: 9pt; margin-bottom: 4pt; }
.retest { color: #b45309; font-size: 8pt; margin-bottom: 4pt; }
.meta-grid {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 1pt 10pt;
}
.meta-item { font-size: 8.5pt; padding: 1pt 0; }
.meta-label { color: #64748b; font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.05em; margin-right: 3pt; }
.mono { font-family: "Consolas", "Courier New", monospace; font-size: 8pt; }
.measure-row { display: flex; gap: 16pt; font-size: 8.5pt; padding: 1pt 0; }
.measure-row .meta-label { margin-right: 4pt; }
table.keypoints {
  width: 100%; border-collapse: collapse; margin-top: 2pt;
  font-variant-numeric: tabular-nums;
}
table.keypoints th, table.keypoints td {
  padding: 2pt 6pt; border-bottom: 0.5pt solid #cbd5e1; text-align: right;
}
table.keypoints th:first-child, table.keypoints td:first-child { text-align: left; }
table.keypoints th {
  color: #475569; font-size: 7.5pt; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.two-col {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 12pt; margin-top: 2pt; align-items: start;
}
.col { min-width: 0; }
.schematic { margin-top: 2pt; text-align: center; }
.schematic img { max-width: 100%; max-height: 3.5in; border: 0.5pt solid #cbd5e1; }
.plot { margin-top: 2pt; }
.plot svg { width: 100%; height: auto; }
.notes {
  margin-top: 2pt; font-size: 8pt; white-space: pre-wrap;
  border: 0.5pt solid #cbd5e1; padding: 3pt 5pt; background: #f8fafc;
}
.report-page { break-before: page; page-break-before: always; }
.report-page:first-child { break-before: avoid; page-break-before: avoid; }
"""


_SUMMARY_CSS = """
@page { size: letter; margin: 0.5in; }
body {
  margin: 0; padding: 0;
  font-family: "Segoe UI", Tahoma, Arial, sans-serif;
  font-size: 9pt; line-height: 1.2;
  color: #0f172a; background: white;
}
h1 { font-size: 13pt; margin: 0 0 2pt 0; }
.subtitle { color: #64748b; font-size: 9pt; margin-bottom: 8pt; }
table.summary {
  width: 100%; border-collapse: collapse;
  font-size: 8.5pt; font-variant-numeric: tabular-nums;
  margin-top: 4pt;
}
table.summary th, table.summary td {
  padding: 2pt 5pt;
  border-bottom: 0.5pt solid #cbd5e1;
}
table.summary thead th {
  background: #f1f5f9; color: #334155;
  font-size: 7.5pt; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em;
  text-align: center;
  border-bottom: 1pt solid #94a3b8;
}
table.summary thead .sub {
  font-size: 7pt; font-weight: 500; color: #64748b;
  text-transform: none; letter-spacing: 0;
  border-bottom: 0.5pt solid #cbd5e1;
}
table.summary td.serial {
  font-weight: 600; text-align: left;
  white-space: nowrap;
}
table.summary td.cell {
  text-align: center;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
table.summary td.cell .nf { color: #0f766e; }
table.summary td.cell .gain { color: #b45309; }
table.summary td.cell .sep { color: #94a3b8; padding: 0 2pt; }
table.summary tr.stats td {
  background: #f8fafc; font-weight: 600;
  border-top: 1pt solid #94a3b8;
}
table.summary tr.stats:first-of-type td { border-top: 1pt solid #475569; }
table.summary tr.stats td.label { color: #475569; text-transform: uppercase; font-size: 7.5pt; letter-spacing: 0.04em; }
.legend { margin-top: 6pt; font-size: 8pt; color: #64748b; }
.legend .nf { color: #0f766e; font-weight: 600; }
.legend .gain { color: #b45309; font-weight: 600; }
"""


def _collect_key_freqs(records: list[RunRecord]) -> list[tuple[float, str]]:
    seen: dict[float, str] = {}
    for record in records:
        for key_str in record.summary.key_points:
            try:
                hz = _parse_key_freq_to_hz(key_str)
            except (ValueError, IndexError):
                continue
            seen.setdefault(hz, key_str)
    return sorted(seen.items())


def _band_label(hz: float) -> str:
    mhz = hz / 1e6
    if mhz >= 1000:
        return f"{mhz/1000:.2f} GHz"
    return f"{mhz:.0f} MHz"


def _summary_cell(nf: float | None, gain: float | None) -> str:
    if nf is None or gain is None or not _is_valid_db(nf) or not _is_valid_db(gain):
        return '<span class="sep">—</span>'
    return f'<span class="nf">{nf:.2f}</span><span class="sep">/</span><span class="gain">{gain:.1f}</span>'


def render_summary_matrix(records: list[RunRecord], title: str = "LNA Summary") -> str:
    """Single-page matrix: rows = units, columns = key frequencies, cells = NF / Gain."""
    if not records:
        return (
            f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{escape(title)}</title>'
            f'<style>{_SUMMARY_CSS}</style></head><body><h1>{escape(title)}</h1>'
            f'<p>No runs recorded yet.</p></body></html>'
        )

    bands = _collect_key_freqs(records)
    # Header rows
    band_th = "".join(f'<th>{escape(_band_label(hz))}</th>' for hz, _ in bands)
    band_sub = "".join('<th class="sub">NF (dB) / Gain (dB)</th>' for _ in bands)

    # Data rows
    body_rows: list[str] = []
    nf_columns: list[list[float]] = [[] for _ in bands]
    gain_columns: list[list[float]] = [[] for _ in bands]
    for record in records:
        cells: list[str] = []
        for idx, (_hz, key_str) in enumerate(bands):
            values = record.summary.key_points.get(key_str)
            if not values:
                cells.append(f'<td class="cell">{_summary_cell(None, None)}</td>')
                continue
            nf = values.get("nf_db")
            gain = values.get("gain_db")
            cells.append(f'<td class="cell">{_summary_cell(nf, gain)}</td>')
            if nf is not None and _is_valid_db(nf):
                nf_columns[idx].append(nf)
            if gain is not None and _is_valid_db(gain):
                gain_columns[idx].append(gain)
        body_rows.append(
            f'<tr><td class="serial">{escape(record.serial_number)}</td>{"".join(cells)}</tr>'
        )

    # Stats rows (min / mean / max)
    def stats_row(label: str, kind: str) -> str:
        cells: list[str] = []
        for nf_vals, gain_vals in zip(nf_columns, gain_columns):
            if not nf_vals or not gain_vals:
                cells.append(f'<td class="cell">{_summary_cell(None, None)}</td>')
                continue
            if kind == "min":
                nf, gain = min(nf_vals), min(gain_vals)
            elif kind == "max":
                nf, gain = max(nf_vals), max(gain_vals)
            else:  # mean
                nf = sum(nf_vals) / len(nf_vals)
                gain = sum(gain_vals) / len(gain_vals)
            cells.append(f'<td class="cell">{_summary_cell(nf, gain)}</td>')
        return f'<tr class="stats"><td class="label">{escape(label)}</td>{"".join(cells)}</tr>'

    stats_html = stats_row("min", "min") + stats_row("mean", "mean") + stats_row("max", "max")

    timestamp = records[0].timestamp_utc.strftime("%Y-%m-%d")
    station = records[0].station_name

    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />'
        f'<title>{escape(title)}</title>'
        f'<style>{_SUMMARY_CSS}</style></head>'
        '<body>'
        f'<h1>{escape(title)}</h1>'
        f'<div class="subtitle">{escape(station)} &middot; {len(records)} units &middot; latest run per serial &middot; generated {escape(timestamp)}</div>'
        '<table class="summary">'
        '<thead>'
        f'<tr><th rowspan="2">Serial</th>{band_th}</tr>'
        f'<tr>{band_sub}</tr>'
        '</thead>'
        f'<tbody>{"".join(body_rows)}{stats_html}</tbody>'
        '</table>'
        '<div class="legend">Each cell shows <span class="nf">NF (dB)</span> / <span class="gain">Gain (dB)</span> at the precise key-frequency measurement. — = no data.</div>'
        '</body></html>'
    )


class CompactHtmlReportGenerator:
    def __init__(self, output_dir: str | Path, doc_dir: str | Path | None = None) -> None:
        self._output_dir = Path(output_dir)
        self._doc_dir = Path(doc_dir) if doc_dir is not None else None

    def write_report(self, record: RunRecord, previous_record: RunRecord | None = None) -> Path:
        reports_dir = self._output_dir / "reports" / record.serial_number
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp_slug = record.timestamp_utc.strftime("%Y%m%dT%H%M%SZ")
        report_path = reports_dir / f"{record.serial_number}_{timestamp_slug}.html"
        report_path.write_text(self._render(record, previous_record), encoding="utf-8")
        return report_path

    def render_combined(self, records: list[RunRecord], title: str = "LNA Batch Report") -> str:
        """Render multiple records as one HTML document with hard page-breaks between units."""
        bodies = "".join(
            f'<div class="report-page">{self._render_body(record, None)}</div>' for record in records
        )
        return (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />'
            f'<title>{escape(title)}</title><style>{_REPORT_CSS}</style></head>'
            f'<body>{bodies}</body></html>'
        )

    def _render(self, record: RunRecord, previous_record: RunRecord | None) -> str:
        body = self._render_body(record, previous_record)
        return (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />'
            f'<title>LNA Report {escape(record.serial_number)}</title>'
            f'<style>{_REPORT_CSS}</style></head>'
            f'<body>{body}</body></html>'
        )

    def _render_body(self, record: RunRecord, previous_record: RunRecord | None) -> str:
        key_points_rows = "".join(
            f'<tr><td>{escape(freq)}</td><td>{values["nf_db"]:.2f}</td><td>{values["gain_db"]:.2f}</td></tr>'
            for freq, values in record.summary.key_points.items()
        )

        retest_line = ""
        if previous_record is not None:
            retest_line = (
                f'<div class="retest">Retest of <span class="mono">{escape(previous_record.run_id[:8])}</span> '
                f'({escape(previous_record.timestamp_utc.isoformat(timespec="seconds"))})</div>'
            )

        schematic_img = _embed_schematic_image(self._doc_dir)
        plot_svg = _combined_plot(record)
        plot_html = (
            '<h2>NF &amp; Gain vs Frequency</h2>'
            f'<div class="plot">{plot_svg}</div>'
            if plot_svg else ""
        )

        keypoints_table = (
            '<table class="keypoints">'
            '<thead><tr><th>Frequency</th><th>NF (dB)</th><th>Gain (dB)</th></tr></thead>'
            f'<tbody>{key_points_rows}</tbody>'
            '</table>'
        )
        if schematic_img:
            details_html = (
                '<div class="two-col">'
                '  <div class="col"><h2>Schematic</h2>'
                f'  <div class="schematic">{schematic_img}</div></div>'
                '  <div class="col"><h2>Key Frequencies</h2>'
                f'  {keypoints_table}</div>'
                '</div>'
            )
        else:
            details_html = f'<h2>Key Frequencies</h2>{keypoints_table}'

        bw = _format_bw(record.measurement_bandwidth_hz)
        n_avg = record.key_point_averages if record.key_point_averages > 0 else "n/a"
        sweep_span = _format_sweep_span(record)

        timestamp = record.timestamp_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        notes_html = (
            f'<div class="notes">{escape(record.notes)}</div>' if record.notes.strip() else ""
        )

        return f"""
<h1>LNA Characterization — {escape(record.serial_number)}</h1>
<div class="subtitle">{escape(timestamp)} &middot; {escape(record.station_name)} &middot; {escape(record.instrument_id)}</div>
{retest_line}

<div class="meta-grid">
  <div class="meta-item"><span class="meta-label">Serial</span>{escape(record.serial_number)}</div>
  <div class="meta-item"><span class="meta-label">Preamp Version</span>{escape(record.preamp_version)}</div>
  <div class="meta-item"><span class="meta-label">Operator</span>{escape(record.operator) or "&mdash;"}</div>
  <div class="meta-item"><span class="meta-label">Noise Head</span>{escape(record.noise_head_id)}</div>
  <div class="meta-item"><span class="meta-label">Run ID</span><span class="mono">{escape(record.run_id[:8])}</span></div>
  <div class="meta-item"><span class="meta-label">Retest</span>{"Yes" if record.is_retest else "No"}</div>
</div>

<h2>Measurement</h2>
<div class="measure-row">
  <span><span class="meta-label">Key-freq BW</span>{escape(bw)}</span>
  <span><span class="meta-label">Averaging</span>N = {n_avg}</span>
  <span><span class="meta-label">Sweep</span>{escape(sweep_span)}</span>
</div>

{plot_html}

{details_html}

{('<h2>Notes</h2>' + notes_html) if notes_html else ''}
"""
