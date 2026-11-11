"""
===================================================================================
 Experimento 9: Medição de DMRT por Medições Nomeadas (200 Leituras por Medição)
 Métricas: DMRT, MRT (Sensoriamento e Referência) e RSSI
===================================================================================
 Descrição:
  - Executa leituras da métrica diferencial DMRT (GreenTag, ACM TOSN 2025)
    baseadas no par de tags configurado para o Experimento 9:
      * Tag de Sensoriamento : E2806995000050136FD0C175 (no substrato do vaso - Experimento 9)
      * Tag de Referência    : E2806995000050136FD0B975 (isolada / referência - Experimento 7)
  - Permite chamar o script livremente, nomeando cada medição da forma desejada
    (via argumento posicional, flag --nome / -n / --medicao / -m, ou prompt interativo).
  - Realiza 200 medições (varreduras de potência RF) por execução (configurável via --readings).
  - Compila automaticamente os dados de cada leitura nomeada em experimento_9/:
      * CSV individual com as 200 leituras (<nome>_resultados.csv)
      * Gráfico temporal da medição (<nome>_grafico.png)
      * Resumo compilado na tabela geral (experimento_9/consolidado_exp9.csv)
===================================================================================
 Exemplos de uso (chame da forma que preferir):
   # 1. Passando o nome diretamente como argumento posicional
   python main.py amostra_1_mineral
   python main.py "Amostra 2 - Solo Turfa"
   python main.py vaso_1_teste_a

   # 2. Passando com --nome (-n) ou --medicao (-m)
   python main.py --nome amostra_1_mineral
   python main.py -n "Solo Horizonte A"
   python main.py --medicao amostra_3

   # 3. Chamando sem argumentos (pergunta o nome interativamente no terminal)
   python main.py

   # 4. Visualizar resumo das medições compiladas no CSV
   python main.py --status
===================================================================================
"""

import os
import re
import sys
import time
import csv
import math
import random
import unicodedata
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from in_r200_driver import INR200Reader
from mrt_calculator import MRTCalculator
from dmrt_exporter import DMRTExporter

# Diretórios e caminhos padrão do Experimento 9
EXP9_DIR = "experimento_9"
DEFAULT_MD_FILE = os.path.join(EXP9_DIR, "experimento9.md")
DEFAULT_JSON_FILE = "tags_mapeadas.json"
CONSOLIDATED_CSV = os.path.join(EXP9_DIR, "consolidado_exp9.csv")

# Padrão: 200 medições (varreduras) por chamada
DEFAULT_TARGET_READINGS = 200
TAG_TIMEOUT = 10.0

# Tags padrão configuradas para o Experimento 9 (Sensoriamento Exp 9 + Referência Exp 7)
DEFAULT_SENSING_EPC = "E2806995000040136FD0C575"
DEFAULT_REF_EPC     = "E2806995000040136FD0C975"

# Curva empírica de referência (Experimento 6) usada apenas para o modo --simulado
EXP6_CURVE = [
    (22.0, 15.00), (30.0, 15.11), (45.0, 15.62), (55.0, 17.47),
    (65.0, 20.40), (78.0, 24.68), (93.0, 25.56)
]

# Colunas oficiais do CSV consolidado
CONSOLIDATED_FIELDS = [
    "medicao",
    "medicao_codigo",
    "nome_medicao",
    "vaso",
    "umidade_rainpoint_pct",
    "umidade_groundtruth_pct",
    "erro_rainpoint_vs_gt_pct",
    "leituras_planejadas",
    "leituras_executadas",
    "leituras_detectadas_sens",
    "leituras_detectadas_ref",
    "leituras_detectadas_dmrt",
    "taxa_deteccao_dmrt_pct",
    "sensing_mrt_raw_medio",
    "sensing_mrt_raw_std",
    "sensing_mrt_filt_medio",
    "sensing_mrt_filt_std",
    "ref_mrt_raw_medio",
    "ref_mrt_raw_std",
    "ref_mrt_filt_medio",
    "ref_mrt_filt_std",
    "dmrt_medio",
    "dmrt_std",
    "dmrt_min",
    "dmrt_max",
    "sensing_rssi_medio",
    "sensing_rssi_std",
    "ref_rssi_medio",
    "ref_rssi_std",
    "sensing_epc",
    "reference_epc",
    "arquivo_csv",
    "arquivo_grafico",
    "data_hora",
]

# Armazenamento em memória das tags escaneadas
scanned_tags: Dict[str, dict] = {}


# ===================================================================================
# Utilitários de Nomeação e Formatação
# ===================================================================================

def slugify_name(name: str) -> str:
    """
    Converte qualquer nome livre de medição em um identificador seguro para arquivos.
    Ex: 'Amostra 1 - Solo Mineral' -> 'amostra_1_solo_mineral'
        '3' -> 'medicao_03'
    """
    raw = name.strip()
    if raw.isdigit():
        return f"medicao_{int(raw):02d}"

    normalized = unicodedata.normalize("NFKD", raw)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text.lower()).strip("_")
    return slug or f"medicao_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def format_display_name(name: str) -> str:
    """Retorna um rótulo legível para exibição no terminal."""
    raw = name.strip()
    if raw.isdigit():
        return f"Medição {int(raw):02d}"
    return raw


# ===================================================================================
# Simulação Virtual (Mock) para Testes Offline do Experimento 9
# ===================================================================================

def _interp_exp6_curve(moisture_pct: float) -> float:
    """Interpola linearmente a curva Umidade -> MRT do Experimento 6."""
    pts = EXP6_CURVE
    if moisture_pct <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        if x0 <= moisture_pct <= x1:
            return y0 + (y1 - y0) * (moisture_pct - x0) / (x1 - x0)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    return y1 + (y1 - y0) / (x1 - x0) * (moisture_pct - x1)


class MockReaderForExp9:
    """Simulador físico para testes offline do Experimento 9."""
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200,
                 sensing_epc: str = DEFAULT_SENSING_EPC, ref_epc: str = DEFAULT_REF_EPC,
                 moisture_pct: Optional[float] = None, medicao_label: str = "medicao_01"):
        self.port = port
        self.baudrate = baudrate
        self.sensing_epc = sensing_epc.upper()
        self.ref_epc = ref_epc.upper()
        self.moisture_pct = moisture_pct if moisture_pct is not None else 55.0
        self.medicao_label = medicao_label
        self.power = 26.0
        self.is_reading = False
        self._sweep_thresholds: Optional[Tuple[float, float]] = None

    def connect(self) -> bool:
        print(f"⚡ [MODO SIMULADO EXP9] Conectado virtualmente em {self.port} ({self.medicao_label})")
        return True

    def get_module_info(self) -> str:
        return "IN-R200 M100 V1.0 (SIMULADO EXP9)"

    def set_rf_power(self, power_dbm: float = 26.0, delay: float = 0.0) -> bool:
        if self._sweep_thresholds is None or power_dbm <= 15.0:
            self._sweep_thresholds = self._draw_thresholds()
        self.power = power_dbm
        return True

    def _draw_thresholds(self) -> Tuple[float, float]:
        sens = _interp_exp6_curve(self.moisture_pct) + random.gauss(0.0, 0.65)
        ref = 14.6 + random.gauss(0.0, 0.25)
        return sens, ref

    def read_multi_tag(self, loop_count: int = 3, timeout: float = 0.15,
                       target_epc: Optional[str] = None) -> Dict[str, dict]:
        detected = {}
        if self._sweep_thresholds is None:
            self._sweep_thresholds = self._draw_thresholds()
        sens_thresh, ref_thresh = self._sweep_thresholds

        if self.power >= sens_thresh:
            if target_epc is None or target_epc.upper() == self.sensing_epc:
                rssi = int(-71 + (self.power - sens_thresh) * 1.5 + random.uniform(-1, 1))
                detected[self.sensing_epc] = {"rssi": rssi, "pc": "3400", "count": loop_count}

        if self.power >= ref_thresh:
            if target_epc is None or target_epc.upper() == self.ref_epc:
                rssi = int(-53 + (self.power - ref_thresh) * 1.5 + random.uniform(-1, 1))
                detected[self.ref_epc] = {"rssi": rssi, "pc": "3400", "count": loop_count}

        return detected

    def read_single_tag(self, timeout: float = 0.15):
        tags = self.read_multi_tag(timeout=timeout)
        if tags:
            epc = next(iter(tags))
            return epc, tags[epc]["rssi"], tags[epc]["pc"]
        return None

    def start_inventory(self, tag_callback):
        self.is_reading = True
        for epc, info in self.read_multi_tag().items():
            tag_callback(epc, info["rssi"], info["pc"])

    def stop_inventory(self, delay: float = 0.0):
        self.is_reading = False

    def close(self):
        self.is_reading = False


# ===================================================================================
# Resolução de Tags e Funções Utilitárias
# ===================================================================================

def is_valid_hex_epc(epc: Optional[str]) -> bool:
    """Verifica se a string é um código EPC hexadecimal válido (24 caracteres)."""
    if not epc:
        return False
    clean = epc.strip()
    return len(clean) == 24 and all(c in "0123456789ABCDEFabcdef" for c in clean)


def load_tags_from_markdown(md_path: str = DEFAULT_MD_FILE) -> Tuple[Optional[str], Optional[str]]:
    """Carrega as tags do Experimento 9 do arquivo markdown de documentação."""
    if not os.path.exists(md_path):
        return None, None
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        m_sens = re.search(r"Tag\s+de\s+Sensoriamento[\s:*=`]*([0-9A-Fa-f]{24})", content, re.IGNORECASE)
        m_ref = re.search(r"Tag\s+de\s+Refer[eê]ncia[\s:*=`]*([0-9A-Fa-f]{24})", content, re.IGNORECASE)

        sens = m_sens.group(1).strip().upper() if m_sens else None
        ref = m_ref.group(1).strip().upper() if m_ref else None
        return sens, ref
    except Exception as e:
        print(f"⚠️ Aviso ao ler {md_path}: {e}")
        return None, None


def load_tags_from_json(json_path: str = DEFAULT_JSON_FILE) -> Tuple[Optional[str], Optional[str]]:
    """Carrega o par de tags do Experimento 9 (fallback: 8 e 7) a partir do arquivo JSON."""
    if not os.path.exists(json_path):
        return None, None
    try:
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for exp_id in ("9", "8", "7"):
            pattern = re.compile(rf"Experimento\s+{exp_id}\b", re.IGNORECASE)
            for pair in data.get("pares", []):
                if pattern.search(str(pair.get("experimento", ""))):
                    return pair.get("sensoriamento"), pair.get("referencia")
        return None, None
    except Exception as e:
        print(f"⚠️ Erro ao ler tags do JSON {json_path}: {e}")
        return None, None


def resolve_tags(args) -> Tuple[str, str]:
    """Resolve os EPCs prioritariamente por CLI, markdown, JSON ou constantes padrão."""
    arg_tag = args.tag.strip().upper() if args.tag else None
    arg_ref = args.ref.strip().upper() if args.ref else None

    md_tag, md_ref = load_tags_from_markdown(args.md)
    json_tag, json_ref = load_tags_from_json(DEFAULT_JSON_FILE)

    sensing_epc = arg_tag or md_tag or json_tag or DEFAULT_SENSING_EPC
    ref_epc = arg_ref or md_ref or json_ref or DEFAULT_REF_EPC

    if is_valid_hex_epc(sensing_epc) and is_valid_hex_epc(ref_epc):
        return sensing_epc.upper(), ref_epc.upper()

    print(f"⚠️ Usando tags padrão do Experimento 9: {DEFAULT_SENSING_EPC} / {DEFAULT_REF_EPC}")
    return DEFAULT_SENSING_EPC, DEFAULT_REF_EPC


def calculate_stats(values: List[float]) -> Tuple[float, float, float, float]:
    """Calcula (média, desvio_padrão, mínimo, máximo)."""
    if not values:
        return 0.0, 0.0, 0.0, 0.0
    n = len(values)
    mean_val = sum(values) / n
    variance = sum((x - mean_val) ** 2 for x in values) / n if n > 1 else 0.0
    return mean_val, math.sqrt(variance), min(values), max(values)


def to_float(value) -> Optional[float]:
    """Converte valores do CSV para float, retornando None para vazios/N/A."""
    if value in (None, "", "N/A", "None", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ===================================================================================
# Exibição Formatada no Terminal
# ===================================================================================

def is_tag_active(epc: str, current_time: float) -> bool:
    """Retorna True se a tag foi detectada recentemente."""
    if epc not in scanned_tags:
        return False
    return (current_time - scanned_tags[epc]["last_seen"]) <= TAG_TIMEOUT


def fmt_rssi(value: float) -> str:
    return f"{value:.1f} dBm" if value < 0 else f"-{value:.1f} dBm"


def print_table(
    reading_counter: int,
    target_readings: int,
    med_label: str,
    med_slug: str,
    rainpoint_pct: Optional[float],
    groundtruth_pct: Optional[float],
    sensing_epc: str,
    reference_epc: str,
    sens_hist_filt: List[float],
    sens_hist_rssi: List[float],
    ref_hist_filt: List[float],
    ref_hist_rssi: List[float],
    dmrt_hist: List[float],
    current_time: float
):
    """Exibe tabela no terminal com métricas completas ao vivo e acumuladas."""
    pct = (reading_counter / target_readings) * 100.0

    s_mean_filt = sum(sens_hist_filt) / len(sens_hist_filt) if sens_hist_filt else 0.0
    s_mean_rssi = sum(sens_hist_rssi) / len(sens_hist_rssi) if sens_hist_rssi else 0.0
    r_mean_filt = sum(ref_hist_filt) / len(ref_hist_filt) if ref_hist_filt else 0.0
    r_mean_rssi = sum(ref_hist_rssi) / len(ref_hist_rssi) if ref_hist_rssi else 0.0
    dmrt_mean = sum(dmrt_hist) / len(dmrt_hist) if dmrt_hist else 0.0

    extras = []
    if rainpoint_pct is not None:
        extras.append(f"RAINPOINT: {rainpoint_pct:.1f}%")
    if groundtruth_pct is not None:
        extras.append(f"GT: {groundtruth_pct:.1f}%")
    extra_str = (" | ".join(extras) + " | ") if extras else ""

    header = (f" EXP 9 | MEDIÇÃO: {med_label} | {extra_str}"
              f"Leitura {reading_counter:04d}/{target_readings:04d} ({pct:.1f}%)")
    divider = "+" + "-" * 20 + "+" + "-" * 12 + "+" + "-" * 26 + "+" + "-" * 11 + "+" + "-" * 12 + "+" + "-" * 13 + "+" + "-" * 15 + "+"

    print("\n" + "=" * 118)
    print(f"{header:<118}")
    print("=" * 118)
    print(divider)
    print(f"| {'Medição':<18} | {'Função':<10} | {'Código EPC':<24} | {'RSSI':<9} | {'Raw MRT':<10} | {'Filt. MRT':<11} | {'MRT Médio Acum':<13} |")
    print(divider)

    short_code = med_slug[:18]
    rows = [(short_code, "Sensor", sensing_epc, s_mean_filt), ("", "Referência", reference_epc, r_mean_filt)]
    for label, role, epc, mean_filt in rows:
        if is_tag_active(epc, current_time):
            info = scanned_tags[epc]
            rssi_str = f"{info['rssi']} dBm" if info["rssi"] < 0 else f"-{info['rssi']} dBm"
            raw_str = f"{info['raw_mrt']:.1f} dBm"
            filt_str = f"{info['filtered_mrt']:.2f} dBm"
        else:
            rssi_str, raw_str, filt_str = "Not seen", "N/A", "N/A"
        print(f"| {label:<18} | {role:<10} | {epc:<24} | {rssi_str:<9} | {raw_str:<10} | {filt_str:<11} | {mean_filt:11.2f} dBm |")
    print(divider)

    dmrt_inst = None
    if is_tag_active(sensing_epc, current_time) and is_tag_active(reference_epc, current_time):
        dmrt_inst = scanned_tags[sensing_epc]["filtered_mrt"] - scanned_tags[reference_epc]["filtered_mrt"]
    dmrt_inst_str = f"{dmrt_inst:+.2f} dB" if dmrt_inst is not None else "N/A"
    dmrt_mean_str = f"{dmrt_mean:+.2f} dB" if dmrt_hist else "N/A"

    print(f" ⚖️  DMRT (Sens - Ref) : Instantâneo = {dmrt_inst_str}  |  Médio Acumulado = {dmrt_mean_str}")
    print(f" 📊 Médias Acumuladas  : Sensor MRT = {s_mean_filt:.2f} dBm (RSSI: {fmt_rssi(s_mean_rssi)}) | "
          f"Ref MRT = {r_mean_filt:.2f} dBm (RSSI: {fmt_rssi(r_mean_rssi)})")


# ===================================================================================
# Compilação das Medições no CSV Consolidado
# ===================================================================================

def read_consolidated_list(csv_path: str = CONSOLIDATED_CSV) -> List[dict]:
    """Lê todas as linhas do CSV consolidado preservando a ordem de execução."""
    rows: List[dict] = []
    if not os.path.exists(csv_path):
        return rows
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            for idx, row in enumerate(csv.DictReader(f), start=1):
                if not row.get("medicao"):
                    row["medicao"] = str(idx)
                if not row.get("medicao_codigo"):
                    row["medicao_codigo"] = slugify_name(str(row.get("nome_medicao") or row["medicao"]))
                if not row.get("nome_medicao") or row.get("nome_medicao") == "N/A":
                    row["nome_medicao"] = row["medicao_codigo"]
                rows.append(row)
    except Exception as e:
        print(f"⚠️ Erro ao ler {csv_path}: {e}")
    return rows


def write_consolidated_list(rows: List[dict], csv_path: str = CONSOLIDATED_CSV):
    """Escreve a lista de medições compiladas no CSV consolidado."""
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CONSOLIDATED_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for idx, row in enumerate(rows, start=1):
            row["medicao"] = str(idx)
            clean_row = {k: (str(row[k]) if row.get(k) not in (None, "") else "N/A") for k in CONSOLIDATED_FIELDS}
            writer.writerow(clean_row)
    print(f"📁 Tabela consolidada atualizada: {os.path.abspath(csv_path)}")


def upsert_consolidated_record(record_entry: dict, csv_path: str = CONSOLIDATED_CSV):
    """
    Atualiza uma medição existente (se tiver o mesmo medicao_codigo) ou adiciona
    uma nova linha ao final do consolidado_exp9.csv.
    """
    rows = read_consolidated_list(csv_path)
    target_slug = record_entry.get("medicao_codigo", "")
    updated = False
    for i, r in enumerate(rows):
        if r.get("medicao_codigo") == target_slug:
            record_entry["medicao"] = r.get("medicao", str(i + 1))
            rows[i] = record_entry
            updated = True
            break
    if not updated:
        record_entry["medicao"] = str(len(rows) + 1)
        rows.append(record_entry)
    write_consolidated_list(rows, csv_path)


def _update_individual_csv_groundtruth(ind_csv_path: str, gt_val: float):
    """Atualiza (ou adiciona) a coluna groundtruth_pct no CSV individual da medição, se existir."""
    if not ind_csv_path or not os.path.exists(ind_csv_path):
        return
    try:
        with open(ind_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
        if not rows:
            return
        if "groundtruth_pct" not in fieldnames:
            if "moisture_pct" in fieldnames:
                idx = fieldnames.index("moisture_pct") + 1
                fieldnames.insert(idx, "groundtruth_pct")
            else:
                fieldnames.append("groundtruth_pct")
        for r in rows:
            r["groundtruth_pct"] = f"{gt_val:.2f}"
        with open(ind_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except Exception:
        pass


# ===================================================================================
# Status Consolidado do Experimento 9
# ===================================================================================

def show_experiment_status():
    """Exibe a tabela com todas as medições nomeadas registradas no Experimento 9."""
    records = read_consolidated_list(CONSOLIDATED_CSV)

    print("\n" + "=" * 128)
    print("                      STATUS DO EXPERIMENTO 9: MEDIÇÕES NOMEADAS DE DMRT (200 LEITURAS POR MEDIÇÃO)")
    print("=" * 128)
    print(f"| {'#':<3} | {'Nome / Código da Medição':<26} | {'Leituras':<9} | {'DMRT Médio (±σ)':<18} | "
          f"{'MRT Sensor':<11} | {'MRT Ref':<10} | {'RSSI Sens':<10} | {'RainPoint':<9} | {'GroundTruth':<11} |")
    sep = ("+" + "-" * 5 + "+" + "-" * 28 + "+" + "-" * 11 + "+" + "-" * 20
           + "+" + "-" * 13 + "+" + "-" * 12 + "+" + "-" * 12 + "+" + "-" * 11 + "+" + "-" * 13 + "+")
    print(sep)

    if not records:
        print(f"| {'Nenhuma medição registrada ainda em ' + CONSOLIDATED_CSV:<124} |")
        print(sep)
        print("=" * 128 + "\n")
        return

    for idx, r in enumerate(records, start=1):
        nome = str(r.get("nome_medicao") or r.get("medicao_codigo") or f"medicao_{idx:02d}")[:26]
        rp_val = to_float(r.get("umidade_rainpoint_pct"))
        gt_val = to_float(r.get("umidade_groundtruth_pct"))
        dmrt_val = to_float(r.get("dmrt_medio"))
        dmrt_std = to_float(r.get("dmrt_std"))
        sens_val = to_float(r.get("sensing_mrt_filt_medio"))
        ref_val = to_float(r.get("ref_mrt_filt_medio"))
        rssi_val = to_float(r.get("sensing_rssi_medio"))

        leit_str = f"{r.get('leituras_detectadas_dmrt', '0')}/{r.get('leituras_planejadas', '0')}"
        dmrt_str = f"{dmrt_val:+.2f} ± {(dmrt_std or 0.0):.2f} dB" if dmrt_val is not None else "N/A"
        sens_str = f"{sens_val:.2f} dBm" if sens_val is not None else "-"
        ref_str = f"{ref_val:.2f} dBm" if ref_val is not None else "-"
        rssi_str = f"{rssi_val:.1f} dBm" if rssi_val is not None else "-"
        rp_str = f"{rp_val:.1f}%" if rp_val is not None else "-"
        gt_str = f"{gt_val:.2f}%" if gt_val is not None else "-"

        print(f"| {idx:02d}  | {nome:<26} | {leit_str:<9} | {dmrt_str:<18} | "
              f"{sens_str:<11} | {ref_str:<10} | {rssi_str:<10} | {rp_str:<9} | {gt_str:<11} |")

    print(sep)
    print(f"Total de medições registradas: {len(records)} | Arquivo compilado: {CONSOLIDATED_CSV}")
    print("=" * 128 + "\n")


# ===================================================================================
# Pipeline Principal de Execução
# ===================================================================================

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Experimento 9: Leitura de DMRT por Medições Nomeadas (200 medições por execução)"
    )
    parser.add_argument(
        "nome_pos", nargs="*", default=[],
        help="Nome da medição passado diretamente (ex: python main.py amostra_1_mineral)"
    )
    parser.add_argument(
        "--nome", "-n", "--medicao", "-m", "--etapa", "--amostra", "--name",
        dest="nome_medicao", type=str, default=None,
        help="Nome ou identificação da medição (ex: --nome amostra_1 ou -n 'Solo Turfa')"
    )
    parser.add_argument(
        "--umidade", "--rainpoint", "-u", dest="umidade", type=float, default=None,
        help="(Opcional) Valor de umidade (%%) medido no sensor RainPoint."
    )
    parser.add_argument(
        "--groundtruth", "--gt", dest="groundtruth", type=float, default=None,
        help="(Opcional) Valor de umidade Ground Truth (%%) gravimétrico."
    )
    parser.add_argument(
        "--vaso", "--descricao", dest="vaso", type=str, default=None,
        help="(Opcional) Descrição adicional ou identificação do vaso/substrato."
    )
    parser.add_argument(
        "--readings", "-r", type=int, default=DEFAULT_TARGET_READINGS,
        help=f"Quantidade de leituras/varreduras de DMRT por medição (padrão: {DEFAULT_TARGET_READINGS})"
    )
    parser.add_argument("--dwell", type=float, default=0.12, help="Tempo de permanência RF por nível em segundos (padrão: 0.12s)")
    parser.add_argument("--power-step", type=float, default=1.0, help="Passo de potência em dBm (padrão: 1.0 dBm)")
    parser.add_argument("--min-power", type=float, default=15.0, help="Potência mínima em dBm (padrão: 15.0 dBm)")
    parser.add_argument("--max-power", type=float, default=26.0, help="Potência máxima em dBm (padrão: 26.0 dBm)")
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Porta serial do leitor (padrão: /dev/ttyUSB0)")
    parser.add_argument("--baudrate", type=int, default=115200, help="Baudrate da porta serial (padrão: 115200)")
    parser.add_argument("--md", default=DEFAULT_MD_FILE, help=f"Arquivo markdown do experimento (padrão: {DEFAULT_MD_FILE})")
    parser.add_argument("--tag", default=None, help="EPC da Tag de Sensoriamento (24 caracteres hex)")
    parser.add_argument("--ref", default=None, help="EPC da Tag de Referência (24 caracteres hex)")
    parser.add_argument("--simulado", action="store_true", help="Executa em modo simulador sem hardware físico do leitor")
    parser.add_argument("--status", action="store_true", help="Exibe a tabela consolidada das medições e encerra")
    return parser.parse_args()


def resolve_measurement_name(args) -> str:
    """
    Resolve o nome da medição a partir de:
      1. Flag (--nome / -n / --medicao / -m / --amostra / --etapa)
      2. Argumentos posicionais (python main.py meu_nome_de_medicao)
      3. Prompt interativo no terminal (se chamado sem argumentos)
      4. Nome sequencial automático (medicao_XX) caso não interativo ou em branco
    """
    if args.nome_medicao and args.nome_medicao.strip():
        return args.nome_medicao.strip()

    if args.nome_pos:
        joined = " ".join(args.nome_pos).strip()
        if joined:
            return joined

    existing = read_consolidated_list(CONSOLIDATED_CSV)
    default_auto = f"medicao_{len(existing) + 1:02d}"

    if sys.stdin is not None and sys.stdin.isatty():
        try:
            typed = input(f"📝 Digite o nome desta medição [Enter para '{default_auto}']: ").strip()
            if typed:
                return typed
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

    return default_auto


def main():
    args = parse_arguments()

    # Modo visualização de status
    if args.status:
        show_experiment_status()
        return

    # Resolve o nome da medição
    raw_name = resolve_measurement_name(args)
    med_slug = slugify_name(raw_name)
    med_label = format_display_name(raw_name)

    rainpoint_pct = args.umidade
    groundtruth_pct = args.groundtruth
    vaso = args.vaso.strip() if args.vaso else med_label

    csv_path = os.path.join(EXP9_DIR, f"{med_slug}_resultados.csv")
    chart_path = os.path.join(EXP9_DIR, f"{med_slug}_grafico.png")
    setup_title = f"Experimento 9 - {med_label}"

    # Conecta ao leitor (ou instancia Mock)
    reader = None
    if not args.simulado:
        reader = INR200Reader(port=args.port, baudrate=args.baudrate)
        if not reader.connect():
            print(f"\n❌ Não foi possível conectar ao leitor na porta {args.port}.")
            print(f"👉 Conceda permissão: sudo chmod 666 {args.port}")
            print("👉 Ou execute com flag --simulado para testar offline.")
            sys.exit(1)

    sensing_epc, ref_epc = resolve_tags(args)

    if args.simulado:
        reader = MockReaderForExp9(
            port=args.port,
            baudrate=args.baudrate,
            sensing_epc=sensing_epc,
            ref_epc=ref_epc,
            moisture_pct=rainpoint_pct,
            medicao_label=med_label
        )
        reader.connect()

    target_readings = args.readings

    print("=" * 112)
    print("           IN-R200 UHF RFID Reader - EXPERIMENTO 9: LEITURA DE DMRT POR MEDIÇÃO NOMEADA")
    print("=" * 112)
    print(f"🏷️  Nome da Medição     : {med_label} (código: {med_slug})")
    if rainpoint_pct is not None:
        print(f"💧 Umidade RainPoint   : {rainpoint_pct:.1f}%")
    if groundtruth_pct is not None:
        print(f"🧪 Ground Truth Grav.  : {groundtruth_pct:.2f}%")
    print(f"📌 Tag Sensoriamento   : {sensing_epc} (Substrato / Vaso)")
    print(f"📌 Tag Referência      : {ref_epc} (Isolada / Referência)")
    print(f"⚡ Faixa de Potência   : {args.min_power:.1f} dBm a {args.max_power:.1f} dBm (passo {args.power_step} dBm com early-stop)")
    print(f"⏱️  Tempo Dwell/Nível  : {args.dwell:.3f} s")
    print(f"🎯 Meta de Leituras    : {target_readings} medições de DMRT")
    print(f"📁 Arquivo CSV         : {csv_path}")
    print(f"📈 Gráfico Individual  : {chart_path}")
    print("=" * 112)

    mrt_calc = MRTCalculator(
        reader=reader,
        min_power=args.min_power,
        max_power=args.max_power,
        power_step=args.power_step,
        dwell_time=args.dwell
    )
    exporter = DMRTExporter()
    target_list = [sensing_epc, ref_epc]

    sens_hist_raw: List[float] = []
    sens_hist_filt: List[float] = []
    sens_hist_rssi: List[float] = []
    ref_hist_raw: List[float] = []
    ref_hist_filt: List[float] = []
    ref_hist_rssi: List[float] = []
    dmrt_hist: List[float] = []

    print(f"\n📡 Iniciando as {target_readings} medições de DMRT para '{med_label}'...")
    print("   (Pressione Ctrl+C a qualquer momento para finalizar e salvar os dados parciais)\n")

    reading_counter = 0
    try:
        while reading_counter < target_readings:
            reading_counter += 1
            t_sweep_0 = time.time()

            scan_results = mrt_calc.linear_sweep_details(
                verbose=False,
                target_epcs=target_list,
                early_stop=True
            )
            dt_sweep = time.time() - t_sweep_0

            now = time.time()
            for epc, info in scan_results.items():
                raw_mrt = info["mrt"]
                filt_mrt = mrt_calc.apply_low_pass_filter(epc, raw_mrt)
                if epc not in scanned_tags:
                    scanned_tags[epc] = {"count": 0, "first_seen": now}
                scanned_tags[epc].update({
                    "count": scanned_tags[epc]["count"] + info["count"],
                    "rssi": info["rssi"],
                    "pc": info["pc"],
                    "raw_mrt": raw_mrt,
                    "filtered_mrt": filt_mrt,
                    "last_seen": now,
                })

            current_time = time.time()
            s_data = scanned_tags.get(sensing_epc) if sensing_epc in scan_results else None
            r_data = scanned_tags.get(ref_epc) if ref_epc in scan_results else None

            if s_data:
                sens_hist_raw.append(s_data["raw_mrt"])
                sens_hist_filt.append(s_data["filtered_mrt"])
                sens_hist_rssi.append(s_data["rssi"])
            if r_data:
                ref_hist_raw.append(r_data["raw_mrt"])
                ref_hist_filt.append(r_data["filtered_mrt"])
                ref_hist_rssi.append(r_data["rssi"])

            dmrt_val = None
            if s_data and r_data:
                dmrt_val = MRTCalculator.calculate_dmrt(s_data["filtered_mrt"], r_data["filtered_mrt"])
                dmrt_hist.append(dmrt_val)

            exporter.record_second_full(
                second=reading_counter,
                sensing_raw_mrt=s_data["raw_mrt"] if s_data else None,
                sensing_filt_mrt=s_data["filtered_mrt"] if s_data else None,
                sensing_rssi=s_data["rssi"] if s_data else None,
                ref_raw_mrt=r_data["raw_mrt"] if r_data else None,
                ref_filt_mrt=r_data["filtered_mrt"] if r_data else None,
                ref_rssi=r_data["rssi"] if r_data else None,
                dmrt=dmrt_val,
                moisture_pct=round(rainpoint_pct, 2) if rainpoint_pct is not None else None,
                rotation_deg=0.0,
                position=med_slug
            )

            s_str = f"S:{s_data['filtered_mrt']:.1f}dBm" if s_data else "S:MISS"
            r_str = f"R:{r_data['filtered_mrt']:.1f}dBm" if r_data else "R:MISS"
            d_str = f"DMRT:{dmrt_val:+.2f}dB" if dmrt_val is not None else "DMRT:N/A"
            print(f"  ⚡ [{reading_counter:04d}/{target_readings}] {med_slug} | {s_str} | {r_str} | {d_str} | Tempo: {dt_sweep:.2f}s")

            if reading_counter % 10 == 0 or reading_counter == target_readings:
                print_table(
                    reading_counter, target_readings, med_label, med_slug,
                    rainpoint_pct, groundtruth_pct, sensing_epc, ref_epc,
                    sens_hist_filt, sens_hist_rssi,
                    ref_hist_filt, ref_hist_rssi,
                    dmrt_hist, current_time
                )

    except KeyboardInterrupt:
        print("\n\n⏹️ Coleta interrompida pelo usuário via Ctrl+C.")
    finally:
        reader.set_rf_power(26.0)
        reader.close()

        os.makedirs(EXP9_DIR, exist_ok=True)
        print(f"\n📊 Exportando dados da medição para {csv_path}...")
        exporter.export_experiment_chart(
            chart_filename=chart_path,
            csv_filename=csv_path,
            title_prefix=setup_title
        )
        if groundtruth_pct is not None:
            _update_individual_csv_groundtruth(csv_path, groundtruth_pct)

        s_raw_mean, s_raw_std, _, _ = calculate_stats(sens_hist_raw)
        s_filt_mean, s_filt_std, _, _ = calculate_stats(sens_hist_filt)
        s_rssi_mean, s_rssi_std, _, _ = calculate_stats(sens_hist_rssi)
        r_raw_mean, r_raw_std, _, _ = calculate_stats(ref_hist_raw)
        r_filt_mean, r_filt_std, _, _ = calculate_stats(ref_hist_filt)
        r_rssi_mean, r_rssi_std, _, _ = calculate_stats(ref_hist_rssi)
        dmrt_mean, dmrt_std, dmrt_min, dmrt_max = calculate_stats(dmrt_hist)
        has_dmrt = bool(dmrt_hist)
        executed = max(reading_counter, 1)

        record_entry = {
            "medicao_codigo": med_slug,
            "nome_medicao": med_label,
            "vaso": vaso,
            "umidade_rainpoint_pct": f"{rainpoint_pct:.1f}" if rainpoint_pct is not None else "N/A",
            "umidade_groundtruth_pct": f"{groundtruth_pct:.2f}" if groundtruth_pct is not None else "N/A",
            "erro_rainpoint_vs_gt_pct": (
                f"{(rainpoint_pct - groundtruth_pct):+.2f}"
                if (rainpoint_pct is not None and groundtruth_pct is not None) else "N/A"
            ),
            "leituras_planejadas": target_readings,
            "leituras_executadas": reading_counter,
            "leituras_detectadas_sens": len(sens_hist_filt),
            "leituras_detectadas_ref": len(ref_hist_filt),
            "leituras_detectadas_dmrt": len(dmrt_hist),
            "taxa_deteccao_dmrt_pct": f"{(len(dmrt_hist) / executed * 100.0):.1f}",
            "sensing_mrt_raw_medio": f"{s_raw_mean:.2f}" if sens_hist_raw else "N/A",
            "sensing_mrt_raw_std": f"{s_raw_std:.2f}" if sens_hist_raw else "N/A",
            "sensing_mrt_filt_medio": f"{s_filt_mean:.2f}" if sens_hist_filt else "N/A",
            "sensing_mrt_filt_std": f"{s_filt_std:.2f}" if sens_hist_filt else "N/A",
            "ref_mrt_raw_medio": f"{r_raw_mean:.2f}" if ref_hist_raw else "N/A",
            "ref_mrt_raw_std": f"{r_raw_std:.2f}" if ref_hist_raw else "N/A",
            "ref_mrt_filt_medio": f"{r_filt_mean:.2f}" if ref_hist_filt else "N/A",
            "ref_mrt_filt_std": f"{r_filt_std:.2f}" if ref_hist_filt else "N/A",
            "dmrt_medio": f"{dmrt_mean:.2f}" if has_dmrt else "N/A",
            "dmrt_std": f"{dmrt_std:.2f}" if has_dmrt else "N/A",
            "dmrt_min": f"{dmrt_min:.2f}" if has_dmrt else "N/A",
            "dmrt_max": f"{dmrt_max:.2f}" if has_dmrt else "N/A",
            "sensing_rssi_medio": f"{s_rssi_mean:.1f}" if sens_hist_rssi else "N/A",
            "sensing_rssi_std": f"{s_rssi_std:.2f}" if sens_hist_rssi else "N/A",
            "ref_rssi_medio": f"{r_rssi_mean:.1f}" if ref_hist_rssi else "N/A",
            "ref_rssi_std": f"{r_rssi_std:.2f}" if ref_hist_rssi else "N/A",
            "sensing_epc": sensing_epc,
            "reference_epc": ref_epc,
            "arquivo_csv": csv_path,
            "arquivo_grafico": chart_path,
            "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        upsert_consolidated_record(record_entry, CONSOLIDATED_CSV)

    dmrt_txt = f"{dmrt_mean:+.2f} dB (± {dmrt_std:.2f} dB)" if has_dmrt else "N/A"
    print("\n" + "=" * 112)
    print(f"        RELATÓRIO FINAL: {setup_title.upper()}")
    print("=" * 112)
    print(f"🏷️  Medição          : {med_label} ({med_slug})")
    print(f"📌 Tag Sensoriamento : {sensing_epc} (Substrato / Vaso)")
    print(f"📌 Tag Referência    : {ref_epc} (Isolada / Referência)")
    if rainpoint_pct is not None:
        print(f"💧 Umidade RainPoint : {rainpoint_pct:.1f}%")
    if groundtruth_pct is not None:
        print(f"🧪 Ground Truth Grav.: {groundtruth_pct:.2f}%")
    print(f"🔁 Medições (Sweeps) : {reading_counter} realizadas ({len(dmrt_hist)} leituras válidas de DMRT)")
    print("-" * 112)
    if sens_hist_filt:
        print(f"🎯 Sensor MRT (EMA)  : {s_filt_mean:.2f} dBm  (± {s_filt_std:.2f} dB) | RSSI: {fmt_rssi(s_rssi_mean)}")
    if ref_hist_filt:
        print(f"🎯 Referência MRT    : {r_filt_mean:.2f} dBm  (± {r_filt_std:.2f} dB) | RSSI: {fmt_rssi(r_rssi_mean)}")
    print(f"⚖️  DMRT Médio (ΔMRT): {dmrt_txt}")
    print("-" * 112)
    print(f"👉 RESULTADO [{med_label}]: DMRT = {dmrt_txt}")
    print("=" * 112)
    print(f"✅ CSV individual salvo em        : {os.path.abspath(csv_path)}")
    print(f"✅ Gráfico individual salvo em    : {os.path.abspath(chart_path)}")
    print(f"✅ Dados compilados salvos em     : {os.path.abspath(CONSOLIDATED_CSV)}")
    print("=" * 112)


if __name__ == "__main__":
    main()
