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

    def record_second_full(
        self,
        second: int,
        sensing_raw_mrt: Optional[float] = None,
        sensing_filt_mrt: Optional[float] = None,
        sensing_rssi: Optional[float] = None,
        ref_raw_mrt: Optional[float] = None,
        ref_filt_mrt: Optional[float] = None,
        ref_rssi: Optional[float] = None,
        dmrt: Optional[float] = None
    ):
        """
        Logs complete second-by-second experiment metrics (MRT raw/filt, RSSI, DMRT) for Sensing and Reference tags.
        """
        entry = {
            "second": second,
            "elapsed_seconds": round(time.time() - self.start_time, 2),
            "sensing_raw_mrt": round(sensing_raw_mrt, 2) if sensing_raw_mrt is not None else None,
            "sensing_filt_mrt": round(sensing_filt_mrt, 2) if sensing_filt_mrt is not None else None,
            "sensing_rssi": round(sensing_rssi, 1) if sensing_rssi is not None else None,
            "ref_raw_mrt": round(ref_raw_mrt, 2) if ref_raw_mrt is not None else None,
            "ref_filt_mrt": round(ref_filt_mrt, 2) if ref_filt_mrt is not None else None,
            "ref_rssi": round(ref_rssi, 1) if ref_rssi is not None else None,
            "dmrt": round(dmrt, 2) if dmrt is not None else None
        }
        self.records.append(entry)


    def export_experiment_chart(
        self,
        chart_filename: str = "experimento_2/vaso_vazio_grafico.png",
        csv_filename: str = "experimento_2/vaso_vazio_resultados.csv",
        title_prefix: str = "Experimento 2 - Vaso de Planta Vazio (45 cm)"
    ) -> Optional[str]:
        """
        Generates and saves a 3-panel graphical chart showing MRT, DMRT, and RSSI over time.
        """
        self.export_csv(csv_filename)

        if not self.records:
            print("⚠️ No experiment records available to generate graphic chart.")
            return None

        # Ensure target directory exists
        os.makedirs(os.path.dirname(os.path.abspath(chart_filename)), exist_ok=True)
        filepath = os.path.abspath(chart_filename)

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            seconds = [rec["second"] for rec in self.records]

            # Filter valid records
            sec_s_raw = [r["second"] for r in self.records if r.get("sensing_raw_mrt") is not None]
            s_raw = [r["sensing_raw_mrt"] for r in self.records if r.get("sensing_raw_mrt") is not None]

            sec_s_filt = [r["second"] for r in self.records if r.get("sensing_filt_mrt") is not None]
            s_filt = [r["sensing_filt_mrt"] for r in self.records if r.get("sensing_filt_mrt") is not None]

            sec_r_raw = [r["second"] for r in self.records if r.get("ref_raw_mrt") is not None]
            r_raw = [r["ref_raw_mrt"] for r in self.records if r.get("ref_raw_mrt") is not None]

            sec_r_filt = [r["second"] for r in self.records if r.get("ref_filt_mrt") is not None]
            r_filt = [r["ref_filt_mrt"] for r in self.records if r.get("ref_filt_mrt") is not None]

            sec_dmrt = [r["second"] for r in self.records if r.get("dmrt") is not None]
            val_dmrt = [r["dmrt"] for r in self.records if r.get("dmrt") is not None]

            sec_s_rssi = [r["second"] for r in self.records if r.get("sensing_rssi") is not None]
            s_rssi = [r["sensing_rssi"] for r in self.records if r.get("sensing_rssi") is not None]

            sec_r_rssi = [r["second"] for r in self.records if r.get("ref_rssi") is not None]
            r_rssi = [r["ref_rssi"] for r in self.records if r.get("ref_rssi") is not None]

            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(11, 9), sharex=True, dpi=150)

            # Panel 1: MRT (Bruto vs Filtrado)
            if sec_s_raw:
                ax1.plot(sec_s_raw, s_raw, color="#9ecae1", linestyle="--", linewidth=1, label="Sensoriamento (Bruto)")
            if sec_s_filt:
                ax1.plot(sec_s_filt, s_filt, color="#1f77b4", linestyle="-", linewidth=2, label="Sensoriamento (Filtrado)")
            if sec_r_raw:
                ax1.plot(sec_r_raw, r_raw, color="#fdd0a2", linestyle="--", linewidth=1, label="Referência (Bruto)")
            if sec_r_filt:
                ax1.plot(sec_r_filt, r_filt, color="#ff7f0e", linestyle="-", linewidth=2, label="Referência (Filtrado)")

            ax1.set_title(f"{title_prefix} - Evolução de MRT, DMRT e RSSI", fontsize=13, fontweight="bold", pad=10)
            ax1.set_ylabel("MRT (dBm)", fontsize=11)
            ax1.grid(True, linestyle="--", alpha=0.5)
            ax1.legend(loc="upper right", fontsize=9, frameon=True)

            # Panel 2: DMRT
            if sec_dmrt:
                ax2.plot(sec_dmrt, val_dmrt, color="#2ca02c", linestyle="-", linewidth=2, label="DMRT (Sensoriamento - Referência)")
            ax2.set_ylabel("DMRT (dB)", fontsize=11)
            ax2.grid(True, linestyle="--", alpha=0.5)
            ax2.legend(loc="upper right", fontsize=9, frameon=True)

            # Panel 3: RSSI
            if sec_s_rssi:
                ax3.plot(sec_s_rssi, s_rssi, color="#1f77b4", linestyle="-", linewidth=1.5, label="Sensoriamento RSSI (-dBm)")
            if sec_r_rssi:
                ax3.plot(sec_r_rssi, r_rssi, color="#ff7f0e", linestyle="-", linewidth=1.5, label="Referência RSSI (-dBm)")
            ax3.set_xlabel("Tempo (Segundos)", fontsize=11)
            ax3.set_ylabel("RSSI (-dBm)", fontsize=11)
            ax3.grid(True, linestyle="--", alpha=0.5)
            ax3.legend(loc="upper right", fontsize=9, frameon=True)

            plt.tight_layout()
            plt.savefig(filepath, format="png", bbox_inches="tight")
            plt.close()

            print(f"📈 Gráfico do experimento exportado com sucesso: {filepath}")
            return filepath

        except Exception as e:
            print(f"⚠️ Erro ao gerar gráfico com Matplotlib: {e}")
            return None

    def export_csv(self, filename: str = "dmrt_results.csv") -> str:
        """
        Exports recorded DMRT data to a CSV file.
        """
        if not self.records:
            print("⚠️ No DMRT records available to export to CSV.")
            return ""

        # Determine all fieldnames dynamically
        all_keys = list(dict.fromkeys(k for rec in self.records for k in rec.keys()))
        fieldnames = ["second", "elapsed_seconds"] + [k for k in all_keys if k not in ("second", "elapsed_seconds")]

        os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
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
        if any("sensing_filt_mrt" in rec for rec in self.records):
            return self.export_experiment_chart(chart_filename, csv_filename)

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

