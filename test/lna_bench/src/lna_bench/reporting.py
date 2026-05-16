from __future__ import annotations

import json
from html import escape
from pathlib import Path

from lna_bench.models import RunRecord, SweepTrace


def _format_frequency_label(frequency_hz: float) -> str:
    return f"{frequency_hz / 1_000_000_000:.3f} GHz"


def _svg_plot(
  trace: SweepTrace,
  color: str,
  y_min: float | None = None,
  y_max: float | None = None,
  y_step: float | None = None,
) -> str:
    width = 780
    height = 260
    padding_left = 60
    padding_right = 20
    padding_top = 20
    padding_bottom = 40
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

    points = " ".join(f"{x_coord(x):.2f},{y_coord(y):.2f}" for x, y in zip(trace.frequencies_hz, trace.values))
    grid_lines = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
      x_line = padding_left + plot_width * fraction
      grid_lines.append(
        f'<line x1="{x_line:.1f}" y1="{padding_top}" x2="{x_line:.1f}" y2="{padding_top + plot_height}" stroke="#e2e8f0" stroke-width="1" />'
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
        f'<line x1="{padding_left}" y1="{y_line:.1f}" x2="{padding_left + plot_width}" y2="{y_line:.1f}" stroke="#e2e8f0" stroke-width="1" />'
      )
      y_labels.append(
        f'<text x="10" y="{y_line + 4:.1f}" font-size="12" fill="#334155">{y_value:.0f} {escape(trace.unit)}</text>'
      )

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(trace.label)} plot">'
        + "".join(grid_lines)
        + f'<line x1="{padding_left}" y1="{padding_top + plot_height}" x2="{padding_left + plot_width}" y2="{padding_top + plot_height}" stroke="#0f172a" stroke-width="1.5" />'
        + f'<line x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{padding_top + plot_height}" stroke="#0f172a" stroke-width="1.5" />'
        + f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{points}" />'
        + f'<text x="{padding_left}" y="{height - 10}" font-size="12" fill="#334155">{escape(_format_frequency_label(min_x))}</text>'
        + f'<text x="{padding_left + plot_width - 70}" y="{height - 10}" font-size="12" fill="#334155">{escape(_format_frequency_label(max_x))}</text>'
        + "".join(y_labels)
        + "</svg>"
    )


class HtmlReportGenerator:
    def __init__(self, output_dir: str | Path) -> None:
        self._output_dir = Path(output_dir)

    def write_report(self, record: RunRecord, previous_record: RunRecord | None = None) -> Path:
        reports_dir = self._output_dir / "reports" / record.serial_number
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp_slug = record.timestamp_utc.strftime("%Y%m%dT%H%M%SZ")
        report_path = reports_dir / f"{record.serial_number}_{timestamp_slug}.html"
        report_path.write_text(self._render(record, previous_record), encoding="utf-8")
        return report_path

    def _render(self, record: RunRecord, previous_record: RunRecord | None) -> str:
        comparison_html = ""
        if previous_record is not None:
            comparison_html = (
                "<section><h2>Previous Run</h2>"
                f"<p>Previous run ID: {escape(previous_record.run_id)}<br>"
                f"Previous timestamp: {escape(previous_record.timestamp_utc.isoformat())}</p>"
                "</section>"
            )

        key_points = "".join(
            f"<tr><td>{escape(freq)}</td><td>{values['nf_db']:.3f}</td><td>{values['gain_db']:.3f}</td></tr>"
            for freq, values in record.summary.key_points.items()
        )

        return f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>LNA Report {escape(record.serial_number)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f8fafc;
      --ink: #0f172a;
      --muted: #475569;
      --card: #ffffff;
      --line: #cbd5e1;
      --accent: #0369a1;
      --accent-2: #166534;
    }}
    body {{
      margin: 0;
      padding: 24px;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background: linear-gradient(180deg, #e0f2fe 0%, var(--bg) 180px);
      color: var(--ink);
    }}
    main {{ max-width: 1100px; margin: 0 auto; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 18px;
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
    }}
    h1, h2 {{ margin-top: 0; }}
    .meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .meta div {{ background: #f8fafc; border-radius: 12px; padding: 12px; }}
    .label {{ display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; }}
    .plot-title {{ margin-bottom: 8px; color: var(--muted); }}
    .notes {{ white-space: pre-wrap; background: #f8fafc; border-radius: 12px; padding: 14px; }}
  </style>
</head>
<body>
  <main>
    <section class=\"card\">
      <h1>LNA Characterization Report</h1>
      <div class=\"meta\">
        <div><span class=\"label\">Serial Number</span>{escape(record.serial_number)}</div>
        <div><span class=\"label\">Preamp Version</span>{escape(record.preamp_version)}</div>
        <div><span class=\"label\">Timestamp UTC</span>{escape(record.timestamp_utc.isoformat())}</div>
        <div><span class=\"label\">Station</span>{escape(record.station_name)}</div>
        <div><span class=\"label\">Instrument</span>{escape(record.instrument_id)}</div>
        <div><span class=\"label\">Noise Head</span>{escape(record.noise_head_id)}</div>
        <div><span class=\"label\">Run ID</span>{escape(record.run_id)}</div>
        <div><span class=\"label\">Retest</span>{'Yes' if record.is_retest else 'No'}</div>
      </div>
    </section>

    <section class=\"card\">
      <h2>Engineering Summary</h2>
      <table>
        <thead><tr><th>Frequency</th><th>Noise Figure (dB)</th><th>Gain (dB)</th></tr></thead>
        <tbody>{key_points}</tbody>
      </table>
    </section>

    <section class=\"card\">
      <h2>Noise Figure Sweep</h2>
      <div class=\"plot-title\">{escape(record.nf_trace.label)} ({escape(record.nf_trace.unit)})</div>
      {_svg_plot(record.nf_trace, '#0f766e', y_min=0.0, y_max=6.0, y_step=1.0)}
    </section>

    <section class=\"card\">
      <h2>Gain Sweep</h2>
      <div class=\"plot-title\">{escape(record.gain_trace.label)} ({escape(record.gain_trace.unit)})</div>
      {_svg_plot(record.gain_trace, '#b45309', y_min=0.0, y_max=30.0, y_step=5.0)}
    </section>

    <section class=\"card\">
      <h2>Retest Notes</h2>
      <div class=\"notes\">{escape(record.notes)}</div>
    </section>

    {comparison_html}
  </main>
</body>
</html>
"""


class JsonArtifactWriter:
  def __init__(self, output_dir: str | Path) -> None:
    self._output_dir = Path(output_dir)

  def write_run_data(self, record: RunRecord) -> Path:
    data_dir = self._output_dir / "data" / record.serial_number
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp_slug = record.timestamp_utc.strftime("%Y%m%dT%H%M%SZ")
    data_path = data_dir / f"{record.serial_number}_{timestamp_slug}.json"
    data_path.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
    return data_path
