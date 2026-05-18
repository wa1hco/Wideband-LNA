"""Compact one-page HTML report template for LNA characterization."""

import base64
from html import escape
from pathlib import Path

from lna_bench.models import RunRecord, SweepTrace


def render_compact_report(record: RunRecord, previous_record: RunRecord | None = None, doc_dir: Path | None = None) -> str:
    """Render a compact single-page report optimized for printing.
    
    Args:
        record: The run record to report on.
        previous_record: Optional previous run for comparison.
        doc_dir: Optional path to doc directory to include schematic image.
    """
    key_points = "".join(
        f"<tr><td>{escape(freq)}</td><td>{values['nf_db']:.2f}</td><td>{values['gain_db']:.2f}</td></tr>"
        for freq, values in record.summary.key_points.items()
    )

    # Check for schematic image
    schematic_html = ""
    if doc_dir:
        doc_path = Path(doc_dir)
        # Look for common schematic image files
        for pattern in ["*.pdf", "*.png", "*.jpg", "*.svg"]:
            matches = list(doc_path.glob(pattern))
            if matches:
                # Use first match
                img_path = matches[0]
                # For PDF, we can embed as object; for images, use img tag
                if img_path.suffix.lower() == ".pdf":
                    schematic_html = f"""
  <h2>Schematic</h2>
  <div style="margin-bottom: 10pt; page-break-inside: avoid;">
    <object data="{img_path.relative_to(doc_path.parent)}" type="application/pdf" width="100%" height="400pt" style="border: 0.5pt solid #d1d5db; border-radius: 2pt;"></object>
  </div>"""
                else:
                    schematic_html = f"""
  <h2>Schematic</h2>
  <div style="margin-bottom: 10pt; page-break-inside: avoid;">
    <img src="{img_path.relative_to(doc_path.parent)}" alt="Schematic" style="max-width: 100%; height: auto; border: 0.5pt solid #d1d5db; border-radius: 2pt;" />
  </div>"""
                break

    retest_note = ""
    if previous_record is not None:
        retest_note = f"""
      <p style="margin: 0; font-size: 10px; color: #94a3b8;">
        <strong>Previous:</strong> {escape(previous_record.timestamp_utc.isoformat()[:10])}
      </p>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>LNA {escape(record.serial_number)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    :root {{
      --ink: #0f172a;
      --muted: #64748b;
      --line: #e2e8f0;
      --border: #d1d5db;
    }}
    body {{
      margin: 0;
      padding: 10pt;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      font-size: 10pt;
      color: var(--ink);
      line-height: 1.4;
    }}
    @media print {{
      body {{ margin: 0; padding: 8pt; }}
      h1 {{ margin: 0 0 4pt 0; }}
      h2 {{ margin: 8pt 0 3pt 0; }}
      .page-break {{ page-break-before: always; margin-top: 10pt; }}
    }}
    h1 {{ margin: 0 0 2pt 0; font-size: 18pt; font-weight: 700; }}
    h2 {{ margin: 6pt 0 2pt 0; font-size: 10pt; font-weight: 700; text-transform: uppercase; color: var(--muted); letter-spacing: 0.05em; }}
    .header-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12pt;
      margin-bottom: 8pt;
      padding-bottom: 6pt;
      border-bottom: 1pt solid var(--border);
    }}
    .header-col {{
      display: flex;
      flex-direction: column;
      gap: 2pt;
    }}
    .label {{ font-size: 8pt; text-transform: uppercase; color: var(--muted); letter-spacing: 0.05em; font-weight: 500; }}
    .value {{ font-size: 11pt; font-weight: 500; }}
    .summary-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr 1fr;
      gap: 6pt;
      margin-bottom: 8pt;
      font-size: 9pt;
    }}
    .summary-item {{
      border: 0.5pt solid var(--line);
      padding: 4pt;
      border-radius: 2pt;
      background: #f8fafc;
    }}
    .table-compact {{
      width: 100%;
      border-collapse: collapse;
      font-size: 9pt;
      margin-bottom: 8pt;
    }}
    .table-compact th {{
      background: #f0f4f8;
      padding: 4pt 6pt;
      text-align: left;
      font-weight: 600;
      border: 0.5pt solid var(--border);
    }}
    .table-compact td {{
      padding: 4pt 6pt;
      border-bottom: 0.5pt solid var(--line);
    }}
    .notes {{
      font-size: 8pt;
      white-space: pre-wrap;
      word-wrap: break-word;
      padding: 4pt 6pt;
      background: #f8fafc;
      border-radius: 2pt;
      margin-bottom: 8pt;
      border-left: 2pt solid #0369a1;
    }}
    svg {{
      max-width: 100%;
      height: auto;
    }}
    .plot-section {{
      margin-bottom: 10pt;
    }}
  </style>
</head>
<body>
  <!-- HEADER / TITLE SECTION -->
  <h1>LNA Characterization: {escape(record.serial_number)}</h1>
  
  <div class="header-row">
    <div class="header-col">
      <div class="label">Date & Time (UTC)</div>
      <div class="value">{record.timestamp_utc.strftime('%Y-%m-%d %H:%M')}</div>
    </div>
    <div class="header-col">
      <div class="label">Preamp Version / Operator</div>
      <div class="value">{escape(record.preamp_version)} / {escape(record.operator or 'N/A')}</div>
    </div>
  </div>

  <!-- KEY PERFORMANCE SUMMARY (COMPACT TABLE) -->
  <h2>Key Frequencies (Engineering Summary)</h2>
  <table class="table-compact">
    <thead>
      <tr>
        <th>Frequency</th>
        <th style="text-align: center;">NF (dB)</th>
        <th style="text-align: center;">Gain (dB)</th>
      </tr>
    </thead>
    <tbody>
      {key_points}
    </tbody>
  </table>

  <!-- NOTES (IF ANY) -->
  {f'<h2>Test Notes</h2><div class="notes">{escape(record.notes)}</div>' if record.notes else ''}

  <!-- CALIBRATION & INSTRUMENT INFO (COMPACT) -->
  <h2>Test Setup & Calibration</h2>
  <div class="summary-grid">
    <div class="summary-item">
      <div class="label">Calibration Date</div>
      <div style="font-size: 10pt;">{escape(record.calibration_date or 'N/A')}</div>
    </div>
    <div class="summary-item">
      <div class="label">Fixture Loss</div>
      <div style="font-size: 10pt;">{record.fixture_loss_db:.2f} dB</div>
    </div>
    <div class="summary-item">
      <div class="label">Noise Head</div>
      <div style="font-size: 10pt;">{escape(record.noise_head_id)}</div>
    </div>
    <div class="summary-item">
      <div class="label">Station</div>
      <div style="font-size: 10pt;">{escape(record.station_name)}</div>
    </div>
  </div>

  {retest_note}

  <!-- PAGE 2: DETAILED PLOTS (OPTIONAL, WILL BREAK TO NEW PAGE IF PRINTING) -->
  <div class="page-break">
    <h2>Noise Figure Sweep (Full Frequency Range)</h2>
    <div class="plot-section">
      {_svg_plot_compact(record.nf_trace, '#0f766e', y_min=0.0, y_max=6.0, y_step=1.0)}
    </div>
  </div>

  <div style="margin-top: 10pt;">
    <h2>Gain Sweep (Full Frequency Range)</h2>
    <div class="plot-section">
      {_svg_plot_compact(record.gain_trace, '#b45309', y_min=0.0, y_max=30.0, y_step=5.0)}
    </div>
  </div>

  <!-- FOOTER -->
  <div style="margin-top: 12pt; padding-top: 8pt; border-top: 0.5pt solid var(--border); font-size: 8pt; color: var(--muted);">
    <p style="margin: 0;">
      Run ID: {escape(record.run_id[:16])} | 
      Instrument: {escape(record.instrument_id[:16])}
    </p>
  </div>
</body>
</html>"""


def _svg_plot_compact(
    trace: SweepTrace,
    color: str,
    y_min: float | None = None,
    y_max: float | None = None,
    y_step: float | None = None,
) -> str:
    """Generate compact SVG plot (smaller than main reporting version)."""
    width = 700
    height = 200
    padding_left = 50
    padding_right = 15
    padding_top = 15
    padding_bottom = 30
    plot_width = width - padding_left - padding_right
    plot_height = height - padding_top - padding_bottom

    min_x = min(trace.frequencies_hz)
    max_x = max(trace.frequencies_hz)
    min_y = y_min if y_min is not None else min(trace.values)
    max_y = y_max if y_max is not None else max(trace.values)
    if min_y == max_y:
        min_y -= 1.0
        max_y += 1.0

    def x_coord(value: float) -> float:
        return padding_left + ((value - min_x) / (max_x - min_x or 1.0)) * plot_width

    def y_coord(value: float) -> float:
        return padding_top + (1.0 - ((value - min_y) / (max_y - min_y or 1.0))) * plot_height

    points = " ".join(f"{x_coord(x):.1f},{y_coord(y):.1f}" for x, y in zip(trace.frequencies_hz, trace.values))
    grid_lines = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        x_line = padding_left + plot_width * fraction
        grid_lines.append(
            f'<line x1="{x_line:.1f}" y1="{padding_top}" x2="{x_line:.1f}" y2="{padding_top + plot_height}" stroke="#e2e8f0" stroke-width="0.5" />'
        )

    if y_step is not None and y_step > 0:
        y_values: list[float] = []
        value = min_y
        while value <= max_y + (y_step * 0.001):
            y_values.append(round(value, 6))
            value += y_step
        if not y_values:
            y_values = [min_y, max_y]
    else:
        y_values = [min_y + (max_y - min_y) * f for f in (0.0, 0.25, 0.5, 0.75, 1.0)]

    y_labels = []
    for y_value in y_values:
        y_line = y_coord(y_value)
        grid_lines.append(
            f'<line x1="{padding_left}" y1="{y_line:.1f}" x2="{padding_left + plot_width}" y2="{y_line:.1f}" stroke="#e2e8f0" stroke-width="0.5" />'
        )
        y_labels.append(f'<text x="8" y="{y_line + 3:.1f}" font-size="9" fill="#475569">{y_value:.0f}</text>')

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(trace.label)} plot" style="border: 0.5pt solid #e2e8f0; border-radius: 3pt;">'
        + "".join(grid_lines)
        + f'<line x1="{padding_left}" y1="{padding_top + plot_height}" x2="{padding_left + plot_width}" y2="{padding_top + plot_height}" stroke="#0f172a" stroke-width="1" />'
        + f'<line x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{padding_top + plot_height}" stroke="#0f172a" stroke-width="1" />'
        + f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{points}" />'
        + f'<text x="{padding_left}" y="{height - 4}" font-size="8" fill="#64748b">{_format_frequency_label(min_x)}</text>'
        + f'<text x="{padding_left + plot_width - 60}" y="{height - 4}" font-size="8" fill="#64748b">{_format_frequency_label(max_x)}</text>'
        + f'<text x="2" y="12" font-size="8" fill="#64748b">{escape(trace.label)} ({escape(trace.unit)})</text>'
        + "".join(y_labels)
        + "</svg>"
    )


def _format_frequency_label(frequency_hz: float) -> str:
    """Format frequency for display."""
    return f"{frequency_hz / 1_000_000_000:.3f} GHz"
