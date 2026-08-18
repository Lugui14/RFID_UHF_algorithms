"""
===================================================================================
 DMRT Data Logger & Graphical Chart Exporter
===================================================================================
 Description:
 - Logs second-by-second DMRT measurements for specified cups.
 - Exports a high-resolution graphical line chart (PNG/SVG) upon completion.
 - Saves raw time-series DMRT data to CSV format.
===================================================================================
"""

import os
import csv
import time
from typing import Dict, List, Optional


class DMRTExporter:
    """
    Class to record second-by-second DMRT measurements and export graphical charts.
    """

    def __init__(self):
        self.records: List[dict] = []
        self.start_time = time.time()

    def record_second(self, second: int, dmrt_by_cup: Dict[str, Optional[float]]):
        """
        Logs DMRT measurements for all cups for the given second.
        
        Parameters:
        - second     : Integer second counter
        - dmrt_by_cup: Dictionary mapping cup name -> DMRT value (in dB) or None
        """
        entry = {
            "second": second,
            "elapsed_seconds": round(time.time() - self.start_time, 2)
        }
        for cup_name, val in dmrt_by_cup.items():
            entry[cup_name] = round(val, 2) if val is not None else None

        self.records.append(entry)

    def export_csv(self, filename: str = "dmrt_results.csv") -> str:
        """
        Exports recorded DMRT data to a CSV file.
        """
        if not self.records:
            print("⚠️ No DMRT records available to export to CSV.")
            return ""

        cup_names = sorted(list({k for rec in self.records for k in rec.keys() if k not in ("second", "elapsed_seconds")}))
        fieldnames = ["second", "elapsed_seconds"] + cup_names

        filepath = os.path.abspath(filename)
        with open(filepath, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in self.records:
                writer.writerow(rec)

        print(f"📊 DMRT CSV data exported: {filepath}")
        return filepath

    def export_chart(self, chart_filename: str = "dmrt_results.png", csv_filename: str = "dmrt_results.csv") -> Optional[str]:
        """
        Generates and saves a graphical line chart showing DMRT results over time for each cup.
        """
        self.export_csv(csv_filename)

        if not self.records:
            print("⚠️ No DMRT records available to generate graphic chart.")
            return None

        filepath = os.path.abspath(chart_filename)

        try:
            import matplotlib
            matplotlib.use("Agg")  # Non-interactive backend suitable for headless servers
            import matplotlib.pyplot as plt

            seconds = [rec["second"] for rec in self.records]
            cup_names = sorted(list({k for rec in self.records for k in rec.keys() if k not in ("second", "elapsed_seconds")}))

            plt.figure(figsize=(10, 6), dpi=150)

            styles = [
                {"color": "#1f77b4", "marker": "o", "label": "Copo Direita"},
                {"color": "#ff7f0e", "marker": "s", "label": "Copo Esquerda"},
                {"color": "#2ca02c", "marker": "^", "label": "Cup 3"},
                {"color": "#d62728", "marker": "d", "label": "Cup 4"}
            ]

            for idx, cup_name in enumerate(cup_names):
                style = styles[idx % len(styles)]
                
                x_vals = []
                y_vals = []
                for rec in self.records:
                    if rec.get(cup_name) is not None:
                        x_vals.append(rec["second"])
                        y_vals.append(rec[cup_name])

                if x_vals:
                    plt.plot(
                        x_vals, y_vals,
                        label=f"{cup_name} (DMRT)",
                        color=style["color"],
                        marker=style["marker"],
                        linewidth=2,
                        markersize=5,
                        alpha=0.9
                    )

            plt.title("Differential Minimum Response Threshold (DMRT) Over Time", fontsize=14, fontweight="bold", pad=15)
            plt.xlabel("Time (Seconds)", fontsize=12, labelpad=10)
            plt.ylabel("DMRT (dB)", fontsize=12, labelpad=10)
            plt.grid(True, linestyle="--", alpha=0.6)
            plt.legend(loc="upper right", fontsize=11, frameon=True)
            plt.tight_layout()

            plt.savefig(filepath, format="png", bbox_inches="tight")
            plt.close()

            print(f"📈 DMRT graphic chart exported: {filepath}")
            return filepath

        except ImportError:
            print("⚠️ Matplotlib not installed. Falling back to SVG graphic generation...")
            return self._export_svg_fallback(chart_filename.replace(".png", ".svg"))

    def _export_svg_fallback(self, svg_filename: str) -> str:
        """
        Pure Python fallback to export SVG graphic when Matplotlib is unavailable.
        """
        filepath = os.path.abspath(svg_filename)
        seconds = [rec["second"] for rec in self.records]
        cup_names = sorted(list({k for rec in self.records for k in rec.keys() if k not in ("second", "elapsed_seconds")}))
        
        width = 800
        height = 500
        margin = 60

        all_y = [rec[c] for rec in self.records for c in cup_names if rec.get(c) is not None]
        min_y = min(all_y) - 1.0 if all_y else -5.0
        max_y = max(all_y) + 1.0 if all_y else 5.0
        min_x = min(seconds) if seconds else 1
        max_x = max(seconds) if seconds else 10

        def map_x(val):
            if max_x == min_x:
                return margin + (width - 2 * margin) / 2
            return margin + (val - min_x) / (max_x - min_x) * (width - 2 * margin)

        def map_y(val):
            if max_y == min_y:
                return height / 2
            return height - margin - (val - min_y) / (max_y - min_y) * (height - 2 * margin)

        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]

        svg_lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
            f'<rect width="100%" height="100%" fill="#ffffff"/>',
            f'<text x="{width/2}" y="30" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">DMRT Results Over Time</text>',
            f'<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="#333" stroke-width="2"/>',
            f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="#333" stroke-width="2"/>'
        ]

        for idx, cup_name in enumerate(cup_names):
            color = colors[idx % len(colors)]
            points = []
            for rec in self.records:
                if rec.get(cup_name) is not None:
                    px = map_x(rec["second"])
                    py = map_y(rec[cup_name])
                    points.append(f"{px:.1f},{py:.1f}")

            if points:
                polyline_pts = " ".join(points)
                svg_lines.append(f'<polyline points="{polyline_pts}" fill="none" stroke="{color}" stroke-width="3"/>')
                leg_y = margin + idx * 25
                svg_lines.append(f'<line x1="{width-150}" y1="{leg_y}" x2="{width-120}" y2="{leg_y}" stroke="{color}" stroke-width="3"/>')
                svg_lines.append(f'<text x="{width-110}" y="{leg_y+4}" font-family="sans-serif" font-size="12" fill="#333">{cup_name}</text>')

        svg_lines.append('</svg>')

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(svg_lines))

        print(f"📈 DMRT graphic chart saved (SVG): {filepath}")
        return filepath
