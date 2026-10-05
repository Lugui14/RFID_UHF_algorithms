"""
===================================================================================
 Experimento 6: Variação de Umidade do Solo em 7 Intervalos (Antena 55 cm Acima)
===================================================================================
 Descrição:
 - Mapeia a correlação entre o teor de umidade do solo (% medido pelo RainPoint)
   e o Limiar Mínimo de Resposta (MRT - bruto e filtrado por passa-baixas EMA)
   e RSSI da tag RFID UHF.
 - Antena posicionada a 55 cm acima da tag (visada superior vertical).
 - Tag já mapeada: E2806995000040136FD0B175 (Sensoriamento - Vaso de Turfa).
 - Faixa de potência RF: 15.0 dBm a 26.0 dBm.
 - 7 diferentes intervalos de umidade (iniciando em 22% no solo seco inicial).
 - 1000 leituras consecutivas para cada intervalo com intervalo otimizado (early-stop).
 - Ao término das 1000 leituras, calcula o valor médio de MRT e RSSI, atualiza a
   tabela consolidada e gera o gráfico individual da etapa e a curva consolidada.
===================================================================================
"""

import os
import re
import sys
import time
import csv
import math
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from in_r200_driver import INR200Reader
from mrt_calculator import MRTCalculator
from dmrt_exporter import DMRTExporter

# Quantidade padrão de leituras/varreduras por etapa
DEFAULT_TARGET_READINGS = 1000
TAG_TIMEOUT = 10.0

# Definição das 7 etapas de umidade do Experimento 6
ETAPAS_CONFIG = {
    1: {
        "slug": "umidade_22pct",
        "umidade_padrao": 22.0,
        "label": "Etapa 1: Solo Seco Inicial (22% Umidade)",
    },
    2: {
        "slug": "umidade_30pct",
        "umidade_padrao": 30.0,
        "label": "Etapa 2: Solo com 1ª Adição de Água (30% Umidade)",
    },
    3: {
        "slug": "umidade_45pct",
        "umidade_padrao": 45.0,
        "label": "Etapa 3: Solo com 2ª Adição de Água (45% Umidade)",
    },
    4: {
        "slug": "umidade_55pct",
        "umidade_padrao": 55.0,
        "label": "Etapa 4: Solo com 3ª Adição de Água (55% Umidade)",
    },
    5: {
        "slug": "umidade_65pct",
        "umidade_padrao": 65.0,
        "label": "Etapa 5: Solo com 4ª Adição de Água (65% Umidade)",
    },
    6: {
        "slug": "umidade_78pct",
        "umidade_padrao": 78.0,
        "label": "Etapa 6: Solo com 5ª Adição de Água (78% Umidade)",
    },
    7: {
        "slug": "umidade_93pct",
        "umidade_padrao": 93.0,
        "label": "Etapa 7: Solo Úmido Saturado (93% Umidade)",
    },
}

CONSOLIDATED_CSV = "experimento_6/consolidado_umidade_mrt.csv"
CONSOLIDATED_CHART = "experimento_6/curva_umidade_vs_mrt.png"

# Dicionário de tags detectadas em tempo de execução
scanned_tags: Dict[str, dict] = {}


# ===================================================================================
# Simulação Virtual (Mock) para Testes Offline
# ===================================================================================

class MockReaderForExp6:
    """Simulador para testes offline de execução e exportação do Experimento 6."""
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.power = 26.0
        self.is_reading = False

    def connect(self) -> bool:
        print(f"⚡ [MODO SIMULADO] Conectado virtualmente em {self.port}")
        return True

    def get_module_info(self) -> str:
        return "IN-R200 M100 V1.0 (SIMULADO EXP6)"

    def set_rf_power(self, power_dbm: float = 26.0, delay: float = 0.0) -> bool:
        self.power = power_dbm
        return True

    def read_single_tag(self, timeout: float = 0.15):
        if self.power >= 19.0:
            return "E2806995000040136FD0B175", -70, "3400"
        return None

    def read_multi_tag(self, loop_count: int = 3, timeout: float = 0.15, target_epc: Optional[str] = None):
        if self.power >= 19.0:
            return {"E2806995000040136FD0B175": {"rssi": -70, "pc": "3400", "count": loop_count}}
        return {}

    def start_inventory(self, tag_callback):
        self.is_reading = True
        # Simula resposta: a tag só responde se potência >= 19.0 dBm
        if self.power >= 19.0:
            tag_callback("E2806995000040136FD0B175", -70, "3400")

    def stop_inventory(self, delay: float = 0.0):
        self.is_reading = False

    def close(self):
        self.is_reading = False


# ===================================================================================
# Carregamento de Tags e Arquivos
# ===================================================================================

def load_tags_from_markdown(md_path: str = "experimento_6/experimento6.md") -> Tuple[str, Optional[str]]:
    """
    Carrega a tag principal de sensoriamento e opcionalmente a de referência
    diretamente do arquivo markdown de documentação.
    """
    default_sensing = "E2806995000040136FD0B175"
    default_ref = None

    if not os.path.exists(md_path):
        return default_sensing, default_ref

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        m_sens = re.search(r"Tag.*?(?:Sensoriamento|Alvo|Utilizada)\s*[:=]\s*`?([0-9A-Fa-f]{24})`?", content, re.IGNORECASE)
        m_ref = re.search(r"Tag.*?Refer[eê]ncia\s*[:=]\s*`?([0-9A-Fa-f]{24})`?", content, re.IGNORECASE)

        sensing = m_sens.group(1).strip().upper() if m_sens else default_sensing
        reference = m_ref.group(1).strip().upper() if m_ref else None
        return sensing, reference
    except Exception as e:
        print(f"⚠️ Aviso ao ler {md_path}: {e}. Usando tags padrão.")
        return default_sensing, default_ref


def is_tag_active(epc: str, current_time: float) -> bool:
    """Retorna True se a tag foi detectada nos últimos TAG_TIMEOUT segundos."""
    if epc not in scanned_tags:
        return False
    return (current_time - scanned_tags[epc]["last_seen"]) <= TAG_TIMEOUT


# ===================================================================================
# Exibição Formatada no Terminal
# ===================================================================================

def print_table(
    reading_counter: int,
    target_readings: int,
    etapa_num: int,
    moisture_pct: float,
    sensing_epc: str,
    reference_epc: Optional[str],
    sensing_history_raw: List[float],
    sensing_history_filt: List[float],
    sensing_history_rssi: List[float],
    current_time: float
):
    """
    Imprime a tabela formatada com métricas ao vivo e médias em tempo real.
    """
    pct = (reading_counter / target_readings) * 100.0
    mean_raw = sum(sensing_history_raw) / len(sensing_history_raw) if sensing_history_raw else 0.0
    mean_filt = sum(sensing_history_filt) / len(sensing_history_filt) if sensing_history_filt else 0.0
    mean_rssi = sum(sensing_history_rssi) / len(sensing_history_rssi) if sensing_history_rssi else 0.0

    header = f" EXPERIMENTO 6 - ETAPA {etapa_num} | UMIDADE RAINPOINT: {moisture_pct:.1f}% | Varredura {reading_counter:04d}/{target_readings:04d} ({pct:.1f}%)"
    divider = "+" + "-" * 17 + "+" + "-" * 12 + "+" + "-" * 26 + "+" + "-" * 11 + "+" + "-" * 13 + "+" + "-" * 15 + "+" + "-" * 16 + "+"

    print("\n" + "=" * 116)
    print(f"{header:<116}")
    print("=" * 116)
    print(divider)
    print(f"| {'Setup / Umidade':<15} | {'Função':<10} | {'Código EPC':<24} | {'RSSI':<9} | {'Raw MRT':<11} | {'Filt. MRT':<13} | {'MRT Médio Acum.':<14} |")
    print(divider)

    s_active = is_tag_active(sensing_epc, current_time)
    if s_active:
        info = scanned_tags[sensing_epc]
        rssi_val = info['rssi']
        rssi_str = f"{rssi_val} dBm" if rssi_val < 0 else f"-{rssi_val} dBm"
        raw_mrt_str = f"{info['raw_mrt']:.1f} dBm"
        filt_mrt_str = f"{info['filtered_mrt']:.2f} dBm"
        media_str = f"{mean_filt:.2f} dBm"
    else:
        rssi_str = "Not seen"
        raw_mrt_str = "N/A"
        filt_mrt_str = "N/A"
        media_str = f"{mean_filt:.2f} dBm" if sensing_history_filt else "N/A"

    label_str = f"Umid. {moisture_pct:.1f}%"
    print(f"| {label_str:<15} | {'Sensor':<10} | {sensing_epc:<24} | {rssi_str:<9} | {raw_mrt_str:<11} | {filt_mrt_str:<13} | {media_str:<14} |")

    # Linha da Tag de Referência (se ativa no ambiente)
    if reference_epc and is_tag_active(reference_epc, current_time):
        r_info = scanned_tags[reference_epc]
        r_rssi_val = r_info['rssi']
        r_rssi_str = f"{r_rssi_val} dBm" if r_rssi_val < 0 else f"-{r_rssi_val} dBm"
        r_raw_mrt_str = f"{r_info['raw_mrt']:.1f} dBm"
        r_filt_mrt_str = f"{r_info['filtered_mrt']:.2f} dBm"
        print(f"| {'':<15} | {'Referência':<10} | {reference_epc:<24} | {r_rssi_str:<9} | {r_raw_mrt_str:<11} | {r_filt_mrt_str:<13} | {'':<14} |")

    print(divider)
    mean_rssi_str = f"{mean_rssi:.1f} dBm" if mean_rssi < 0 else f"-{mean_rssi:.1f} dBm"
    print(f" 📊 Médias Acumuladas: MRT Filtrado = {mean_filt:.2f} dBm | MRT Bruto = {mean_raw:.2f} dBm | RSSI = {mean_rssi_str}")


# ===================================================================================
# Consolidação de Dados e Gráficos Globais
# ===================================================================================

def calculate_stats(values: List[float]) -> Tuple[float, float, float, float]:
    """Retorna (média, desvio_padrão, mínimo, máximo)."""
    if not values:
        return 0.0, 0.0, 0.0, 0.0
    n = len(values)
    mean_val = sum(values) / n
    variance = sum((x - mean_val) ** 2 for x in values) / n if n > 1 else 0.0
    std_val = math.sqrt(variance)
    return mean_val, std_val, min(values), max(values)


def update_consolidated_csv(
    csv_path: str,
    etapa: int,
    umidade_pct: float,
    readings_total: int,
    readings_valid: int,
    raw_mrt_mean: float,
    raw_mrt_std: float,
    filt_mrt_mean: float,
    filt_mrt_std: float,
    rssi_mean: float,
    rssi_std: float,
    dmrt_mean: Optional[float]
):
    """
    Atualiza ou insere o registro da etapa no CSV consolidado de Experimento 6.
    """
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    rows_by_etapa = {}

    if os.path.exists(csv_path):
        try:
            with open(csv_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        e = int(row["etapa"])
                        rows_by_etapa[e] = row
                    except (ValueError, KeyError):
                        pass
        except Exception as e:
            print(f"⚠️ Aviso ao ler consolidado existente: {e}")

    # Atualiza ou cria linha da etapa
    rssi_dbm_str = f"{rssi_mean:.1f}" if rssi_mean < 0 else f"-{rssi_mean:.1f}"
    rows_by_etapa[etapa] = {
        "etapa": etapa,
        "umidade_pct": f"{umidade_pct:.1f}",
        "leituras_planejadas": readings_total,
        "leituras_detectadas": readings_valid,
        "taxa_deteccao_pct": f"{(readings_valid / readings_total * 100.0):.1f}" if readings_total > 0 else "0.0",
        "mrt_bruto_medio_dbm": f"{raw_mrt_mean:.2f}",
        "mrt_bruto_std_db": f"{raw_mrt_std:.2f}",
        "mrt_filtrado_medio_dbm": f"{filt_mrt_mean:.2f}",
        "mrt_filtrado_std_db": f"{filt_mrt_std:.2f}",
        "rssi_medio_dbm": rssi_dbm_str,
        "rssi_std_db": f"{rssi_std:.2f}",
        "dmrt_medio_db": f"{dmrt_mean:.2f}" if dmrt_mean is not None else "N/A",
        "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    fieldnames = [
        "etapa", "umidade_pct", "leituras_planejadas", "leituras_detectadas",
        "taxa_deteccao_pct", "mrt_bruto_medio_dbm", "mrt_bruto_std_db",
        "mrt_filtrado_medio_dbm", "mrt_filtrado_std_db", "rssi_medio_dbm",
        "rssi_std_db", "dmrt_medio_db", "data_hora"
    ]

    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in sorted(rows_by_etapa.keys()):
            writer.writerow(rows_by_etapa[e])

    print(f"📁 Tabela consolidada atualizada: {os.path.abspath(csv_path)}")


def generate_consolidated_chart(csv_path: str, chart_path: str):
    """
    Gera o gráfico consolidado da curva Umidade vs MRT Médio e RSSI Médio
    a partir das etapas concluídas registradas no CSV consolidado.
    """
    if not os.path.exists(csv_path):
        return

    etapas = []
    umidades = []
    mrts = []
    mrt_stds = []
    rssis = []

    try:
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                etapas.append(int(row["etapa"]))
                umidades.append(float(row["umidade_pct"]))
                mrts.append(float(row["mrt_filtrado_medio_dbm"]))
                mrt_stds.append(float(row["mrt_filtrado_std_db"]))
                raw_r = row["rssi_medio_dbm"].strip()
                r_val = float(raw_r) if raw_r != "N/A" else 0.0
                rssis.append(r_val)

        if len(umidades) < 2:
            return  # Gera a curva comparativa quando houver 2 ou mais etapas

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax1 = plt.subplots(figsize=(10, 6), dpi=150)

        color_mrt = "#1f77b4"
        ax1.set_xlabel("Umidade do Solo - Sensor RainPoint (%)", fontsize=12, fontweight="bold")
        ax1.set_ylabel("MRT Médio Filtrado (dBm)", color=color_mrt, fontsize=12, fontweight="bold")
        line1 = ax1.errorbar(
            umidades, mrts, yerr=mrt_stds, fmt='-o', color=color_mrt,
            linewidth=2, markersize=7, capsize=5, label="MRT Médio (dBm)"
        )
        ax1.tick_params(axis='y', labelcolor=color_mrt)
        ax1.grid(True, linestyle="--", alpha=0.5)

        # Eixo secundário para RSSI
        ax2 = ax1.twinx()
        color_rssi = "#ff7f0e"
        ax2.set_ylabel("RSSI Médio (dBm)", color=color_rssi, fontsize=12, fontweight="bold")
        line2 = ax2.plot(
            umidades, rssis, '-s', color=color_rssi, linewidth=2,
            markersize=7, label="RSSI Médio (dBm)"
        )
        ax2.tick_params(axis='y', labelcolor=color_rssi)

        # Limites adequados para evitar sobreposição de textos com a moldura
        ax1.set_ylim(min(mrts) - 1.0, max(mrts) + 1.8)
        ax2.set_ylim(min(rssis) - 1.2, max(rssis) + 1.2)

        for i, txt in enumerate(etapas):
            offset_y = 14 if i % 2 == 0 else 16
            ax1.annotate(
                f"E{txt} ({umidades[i]:.0f}%)\n{mrts[i]:.2f} dBm",
                (umidades[i], mrts[i]),
                textcoords="offset points",
                xytext=(0, offset_y),
                fontsize=8.5,
                fontweight="bold",
                ha='center',
                color="#0e4b75",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.75, edgecolor="none")
            )

        # Legenda combinada para ambos os eixos no canto superior esquerdo (área livre)
        lines = [line1, line2[0]]
        labels = [l.get_label() for l in lines]
        ax1.legend(lines, labels, loc="upper left", framealpha=0.9, fontsize=10)

        plt.title("Experimento 6: Correlação entre Umidade do Solo, MRT Médio e RSSI\n(Antena 55 cm Acima do Vaso de Turfa)", fontsize=13, fontweight="bold", pad=12)
        fig.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(chart_path)), exist_ok=True)
        plt.savefig(chart_path, format="png", bbox_inches="tight")
        plt.close()
        print(f"📈 Gráfico consolidado Umidade vs MRT gerado: {os.path.abspath(chart_path)}")
    except Exception as e:
        print(f"⚠️ Não foi possível gerar gráfico consolidado: {e}")


# ===================================================================================
# Função Principal (Pipeline do Experimento 6)
# ===================================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Experimento 6: Mapeamento de 7 Intervalos de Umidade do Solo com MRT e RSSI (Antena 55 cm Acima)"
    )
    parser.add_argument(
        "--etapa", type=int, choices=[1, 2, 3, 4, 5, 6, 7], default=1,
        help="Etapa do experimento (1 a 7). Padrão: 1 (Solo Seco 22%%)"
    )
    parser.add_argument(
        "--umidade", type=float, default=None,
        help="Porcentagem de umidade do solo lida no RainPoint (sobrescreve o padrão da etapa)"
    )
    parser.add_argument(
        "--readings", type=int, default=DEFAULT_TARGET_READINGS,
        help=f"Quantidade de leituras/varreduras por etapa (padrão: {DEFAULT_TARGET_READINGS})"
    )
    parser.add_argument(
        "--dwell", type=float, default=0.12,
        help="Tempo de permanência em cada potência RF em segundos (padrão: 0.12s para rajada multi-round síncrona)"
    )
    parser.add_argument(
        "--power-step", type=float, default=1.0,
        help="Passo de incremento de potência RF em dBm (padrão: 1.0 dBm - resolução do hardware)"
    )
    parser.add_argument(
        "--min-power", type=float, default=15.0,
        help="Potência mínima de varredura RF em dBm (padrão: 15.0 - limite de hardware)"
    )
    parser.add_argument(
        "--max-power", type=float, default=26.0,
        help="Potência máxima de varredura RF em dBm (padrão: 26.0 - limite de hardware)"
    )
    parser.add_argument(
        "--port", default="/dev/ttyUSB0",
        help="Porta serial do leitor (padrão: /dev/ttyUSB0)"
    )
    parser.add_argument(
        "--baudrate", type=int, default=115200,
        help="Baudrate da porta serial (padrão: 115200)"
    )
    parser.add_argument(
        "--md", default="experimento_6/experimento6.md",
        help="Arquivo markdown com a documentação do experimento"
    )
    parser.add_argument(
        "--tag", default=None,
        help="EPC da tag de sensoriamento (sobrescreve valor lido do markdown)"
    )
    parser.add_argument(
        "--ref", default=None,
        help="EPC da tag de referência opcional (sobrescreve valor lido do markdown)"
    )
    parser.add_argument(
        "--simulado", action="store_true",
        help="Executa em modo virtual de simulação sem leitor físico"
    )

    args = parser.parse_args()

    # 1. Identifica parâmetros da etapa
    cfg = ETAPAS_CONFIG[args.etapa]
    umidade_pct = args.umidade if args.umidade is not None else cfg["umidade_padrao"]
    slug = f"etapa_{args.etapa}_umidade_{umidade_pct:.0f}pct"

    csv_path = f"experimento_6/{slug}_resultados.csv"
    chart_path = f"experimento_6/{slug}_grafico.png"
    setup_title = f"Experimento 6 - Etapa {args.etapa} (Umidade {umidade_pct:.1f}% - Antena 55cm)"
    setup_label = f"Etapa {args.etapa} ({umidade_pct:.0f}%)"

    # 2. Carrega tags do markdown ou argumentos
    md_sensing, md_ref = load_tags_from_markdown(args.md)
    sensing_epc = args.tag.strip().upper() if args.tag else md_sensing
    reference_epc = args.ref.strip().upper() if args.ref else md_ref

    target_readings = args.readings

    print("=" * 114)
    print("      IN-R200 UHF RFID Reader - EXPERIMENTO 6: 7 INTERVALOS DE UMIDADE DO SOLO")
    print("=" * 114)
    print(f"🔬 Etapa Atual       : {args.etapa} de 7 ({cfg['label']})")
    print(f"💧 Umidade RainPoint : {umidade_pct:.1f}%")
    print(f"📐 Altura da Antena  : 55 cm acima da tag (visada superior vertical)")
    print(f"🏷️  Tag Sensoriamento : {sensing_epc}")
    if reference_epc:
        print(f"🏷️  Tag Referência    : {reference_epc} (opcional)")
    print(f"⚡ Faixa de Potência : {args.min_power:.1f} dBm a {args.max_power:.1f} dBm (passo 1.0 dBm com early-stop)")
    print(f"⏱️  Tempo Dwell/Nível: {args.dwell:.3f} s (otimizado para leituras rápidas)")
    print(f"🎯 Meta de Leituras  : {target_readings} varreduras")
    print(f"📁 Arquivo CSV       : {csv_path}")
    print(f"📈 Gráfico PNG       : {chart_path}")
    print("=" * 114)

    # 3. Conecta ao leitor
    if args.simulado:
        reader = MockReaderForExp6(port=args.port, baudrate=args.baudrate)
    else:
        reader = INR200Reader(port=args.port, baudrate=args.baudrate)

    if not reader.connect():
        print(f"\n❌ Não foi possível conectar ao leitor em {args.port}.")
        print(f"👉 Verifique permissões: sudo chmod 666 {args.port}")
        print("👉 Ou execute com --simulado para testar offline.")
        sys.exit(1)

    # 4. Inicializa calculadora MRT com passo de potência do hardware e rajada multi-round
    mrt_calc = MRTCalculator(
        reader=reader,
        min_power=args.min_power,
        max_power=args.max_power,
        power_step=args.power_step,
        dwell_time=args.dwell
    )

    # 5. Inicializa exportador de dados
    exporter = DMRTExporter()

    # Histórico de métricas da tag de sensoriamento para estatísticas em tempo real
    sensing_history_raw: List[float] = []
    sensing_history_filt: List[float] = []
    sensing_history_rssi: List[float] = []
    dmrt_history: List[float] = []

    target_list = [sensing_epc]
    if reference_epc:
        target_list.append(reference_epc)

    print(f"\n📡 Iniciando as {target_readings} leituras com intervalo acelerado...")
    print("   (Você pode interromper a qualquer momento com Ctrl+C para finalizar e consolidar os dados)\n")

    reading_counter = 0

    try:
        while reading_counter < target_readings:
            reading_counter += 1
            t_sweep_0 = time.time()

            # Executa varredura linear com parada antecipada (early_stop) assim que as tags alvo respondem
            scan_results = mrt_calc.linear_sweep_details(
                verbose=False,
                target_epcs=target_list,
                early_stop=True
            )
            dt_sweep = time.time() - t_sweep_0

            # Atualiza dados de todas as tags detectadas
            now = time.time()
            for epc, info in scan_results.items():
                raw_mrt = info["mrt"]
                filtered_mrt = mrt_calc.apply_low_pass_filter(epc, raw_mrt)

                if epc not in scanned_tags:
                    scanned_tags[epc] = {
                        "count": info["count"],
                        "rssi": info["rssi"],
                        "pc": info["pc"],
                        "raw_mrt": raw_mrt,
                        "filtered_mrt": filtered_mrt,
                        "first_seen": now,
                        "last_seen": now
                    }
                else:
                    scanned_tags[epc]["count"] += info["count"]
                    scanned_tags[epc]["rssi"] = info["rssi"]
                    scanned_tags[epc]["pc"] = info["pc"]
                    scanned_tags[epc]["raw_mrt"] = raw_mrt
                    scanned_tags[epc]["filtered_mrt"] = filtered_mrt
                    scanned_tags[epc]["last_seen"] = now

            current_time = time.time()
            s_current_seen = sensing_epc in scan_results
            r_current_seen = reference_epc in scan_results if reference_epc else False

            s_data = scanned_tags.get(sensing_epc) if s_current_seen else None
            r_data = scanned_tags.get(reference_epc) if r_current_seen else None

            # Registra no histórico para cálculo das médias APENAS se detectado nesta rodada
            if s_data:
                sensing_history_raw.append(s_data["raw_mrt"])
                sensing_history_filt.append(s_data["filtered_mrt"])
                sensing_history_rssi.append(s_data["rssi"])

            dmrt_val = None
            if s_data and r_data:
                dmrt_val = MRTCalculator.calculate_dmrt(
                    s_data["filtered_mrt"],
                    r_data["filtered_mrt"]
                )
                dmrt_history.append(dmrt_val)

            # Grava no exportador
            exporter.record_second_full(
                second=reading_counter,
                sensing_raw_mrt=s_data["raw_mrt"] if s_data else None,
                sensing_filt_mrt=s_data["filtered_mrt"] if s_data else None,
                sensing_rssi=s_data["rssi"] if s_data else None,
                ref_raw_mrt=r_data["raw_mrt"] if r_data else None,
                ref_filt_mrt=r_data["filtered_mrt"] if r_data else None,
                ref_rssi=r_data["rssi"] if r_data else None,
                dmrt=dmrt_val,
                moisture_pct=umidade_pct
            )

            # Feedback ao vivo a cada varredura (evita sensação de tela travada)
            if s_data:
                r_val = s_data['rssi']
                r_str = f"{r_val} dBm" if r_val < 0 else f"-{r_val} dBm"
                print(f"  ⚡ [{reading_counter:04d}/{target_readings}] MRT: {s_data['raw_mrt']:.1f} dBm (Filt: {s_data['filtered_mrt']:.2f} dBm) | RSSI: {r_str} | Tempo: {dt_sweep:.2f}s")
            else:
                print(f"  ⚠️ [{reading_counter:04d}/{target_readings}] Tag NÃO detectada na faixa {args.min_power:.1f}..{args.max_power:.1f} dBm | Tempo: {dt_sweep:.2f}s")

            # Exibe tabela a cada 10 leituras ou na última leitura para consolidar a visão geral
            if reading_counter % 10 == 0 or reading_counter == target_readings:
                print_table(
                    reading_counter, target_readings, args.etapa, umidade_pct,
                    sensing_epc, reference_epc, sensing_history_raw,
                    sensing_history_filt, sensing_history_rssi, current_time
                )

    except KeyboardInterrupt:
        print("\n\n⏹️ Coleta interrompida antecipadamente pelo usuário via Ctrl+C.")
    finally:
        # Restaura potência e encerra conexão
        reader.set_rf_power(26.0)
        reader.close()

        # Garante diretório de destino
        os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)

        # Exporta gráfico e CSV da etapa atual
        print(f"\n📊 Exportando resultados da Etapa {args.etapa} para {csv_path}...")
        exporter.export_experiment_chart(
            chart_filename=chart_path,
            csv_filename=csv_path,
            title_prefix=setup_title
        )

        # Calcula estatísticas finais
        mean_raw, std_raw, min_raw, max_raw = calculate_stats(sensing_history_raw)
        mean_filt, std_filt, min_filt, max_filt = calculate_stats(sensing_history_filt)
        mean_rssi, std_rssi, min_rssi, max_rssi = calculate_stats(sensing_history_rssi)
        mean_dmrt = sum(dmrt_history) / len(dmrt_history) if dmrt_history else None

        # Atualiza a tabela consolidada de Experimento 6
        update_consolidated_csv(
            csv_path=CONSOLIDATED_CSV,
            etapa=args.etapa,
            umidade_pct=umidade_pct,
            readings_total=reading_counter,
            readings_valid=len(sensing_history_filt),
            raw_mrt_mean=mean_raw,
            raw_mrt_std=std_raw,
            filt_mrt_mean=mean_filt,
            filt_mrt_std=std_filt,
            rssi_mean=mean_rssi,
            rssi_std=std_rssi,
            dmrt_mean=mean_dmrt
        )

        # Gera curva consolidada atualizada
        generate_consolidated_chart(CONSOLIDATED_CSV, CONSOLIDATED_CHART)

    # Relatório Final no Terminal
    rssi_mean_str = f"{mean_rssi:.1f} dBm" if mean_rssi < 0 else f"-{mean_rssi:.1f} dBm"
    print("\n" + "=" * 114)
    print(f"        RELATÓRIO FINAL: {setup_title.upper()}")
    print("=" * 114)
    print(f"📌 Tag de Sensoriamento     : {sensing_epc}")
    print(f"💧 Umidade do Solo Aferida  : {umidade_pct:.1f}% (RainPoint)")
    print(f"📐 Posicionamento da Antena : 55 cm acima da tag")
    print(f"🔢 Total de Varreduras      : {reading_counter} realizadas ({len(sensing_history_filt)} válidas)")
    print("-" * 114)
    print(f"🎯 MRT Bruto Médio          : {mean_raw:.2f} dBm  (± {std_raw:.2f} dB) [Min: {min_raw:.1f}, Max: {max_raw:.1f}]")
    print(f"🎯 MRT Filtrado Médio (EMA) : {mean_filt:.2f} dBm  (± {std_filt:.2f} dB) [Min: {min_filt:.2f}, Max: {max_filt:.2f}]")
    print(f"📶 RSSI Médio               : {rssi_mean_str} (± {std_rssi:.2f} dB)")
    if mean_dmrt is not None:
        print(f"⚖️  DMRT Médio               : {mean_dmrt:+.2f} dB")
    print("-" * 114)
    print(f"👉 MAPEAMENTO FORMAL: Umidade = {umidade_pct:.1f}%  ==>  MRT Médio = {mean_filt:.2f} dBm | RSSI Médio = {rssi_mean_str}")
    print("=" * 114)
    print(f"✅ Arquivo CSV da etapa salvo em : {os.path.abspath(csv_path)}")
    print(f"✅ Gráfico PNG da etapa salvo em : {os.path.abspath(chart_path)}")
    print(f"✅ Tabela consolidada salva em   : {os.path.abspath(CONSOLIDATED_CSV)}")
    if os.path.exists(CONSOLIDATED_CHART):
        print(f"✅ Curva consolidada gerada em   : {os.path.abspath(CONSOLIDATED_CHART)}")
    print("=" * 114)


if __name__ == "__main__":
    main()
