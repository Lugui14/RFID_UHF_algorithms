"""
===================================================================================
 Experimento 7: Invariância Espacial e Angular do DMRT sob Umidade Fixa do Solo
 Métricas: DMRT, MRT (Sensoriamento e Referência) e RSSI
===================================================================================
 Descrição:
 - Avalia a estabilidade da métrica diferencial GreenTag (ACM TOSN 2025) sob uma
   faixa constante e controlada de umidade do solo em duas dimensões de canal:
     1. Variação de Orientação Angular da Tag (Rotações do vaso: 0°, 90°, 180°, 270°)
     2. Deslocamento Espacial do Vaso na Bancada (pos_centro, pos_esq, pos_dir, pos_frente)
 - Duas tags RFID UHF mapeadas:
     * Tag de Sensoriamento : E2806995000050136FD0B575 (no substrato do vaso)
     * Tag de Referência    : E2806995000050136FD0B975 (isolada no ar/referência)
 - Mede para cada combinação:
     * MRT da Tag de Sensoriamento (bruto e filtrado EMA)
     * MRT da Tag de Referência (bruto e filtrado EMA)
     * DMRT (Limiar Mínimo Diferencial: MRT_sens - MRT_ref)
     * RSSI da Tag de Sensoriamento e da Tag de Referência
 - 300 medições por combinação com parada antecipada otimizada (early-stop).
===================================================================================
"""

import os
import re
import sys
import time
import csv
import math
import random
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from in_r200_driver import INR200Reader
from mrt_calculator import MRTCalculator
from dmrt_exporter import DMRTExporter

# Diretórios e caminhos padrão do Experimento 7
EXP7_DIR = "experimento_7"
DEFAULT_MD_FILE = os.path.join(EXP7_DIR, "experimento7.md")
DEFAULT_JSON_FILE = "tags_mapeadas.json"
CONSOLIDATED_CSV = os.path.join(EXP7_DIR, "consolidado_exp7.csv")
CHART_ROTATION_DMRT = os.path.join(EXP7_DIR, "curva_rotacao_vs_dmrt_por_posicao.png")
CHART_SPATIAL_DMRT = os.path.join(EXP7_DIR, "curva_posicoes_espaciais_vs_metricas.png")

DEFAULT_TARGET_READINGS = 300
TAG_TIMEOUT = 10.0

# -----------------------------------------------------------------------------------
# Catálogo das 16 Baterias Padrão (4 Posições Espaciais x 4 Rotações do Vaso Quadrado)
# -----------------------------------------------------------------------------------
BATERIAS_CONFIG = {
    # Bloco 1: Posição Central (Ponto de Referência)
    1:  {"posicao": "pos_centro", "pos_label": "Centro",    "rotacao": 0,   "face": "Face 1 (Frontal)"},
    2:  {"posicao": "pos_centro", "pos_label": "Centro",    "rotacao": 90,  "face": "Face 2 (Lateral Dir.)"},
    3:  {"posicao": "pos_centro", "pos_label": "Centro",    "rotacao": 180, "face": "Face 3 (Traseira)"},
    4:  {"posicao": "pos_centro", "pos_label": "Centro",    "rotacao": 270, "face": "Face 4 (Lateral Esq.)"},

    # Bloco 2: Deslocado para a Esquerda (~15 cm)
    5:  {"posicao": "pos_esq",    "pos_label": "Esquerda",  "rotacao": 0,   "face": "Face 1 (Frontal)"},
    6:  {"posicao": "pos_esq",    "pos_label": "Esquerda",  "rotacao": 90,  "face": "Face 2 (Lateral Dir.)"},
    7:  {"posicao": "pos_esq",    "pos_label": "Esquerda",  "rotacao": 180, "face": "Face 3 (Traseira)"},
    8:  {"posicao": "pos_esq",    "pos_label": "Esquerda",  "rotacao": 270, "face": "Face 4 (Lateral Esq.)"},

    # Bloco 3: Deslocado para a Direita (~15 cm)
    9:  {"posicao": "pos_dir",    "pos_label": "Direita",   "rotacao": 0,   "face": "Face 1 (Frontal)"},
    10: {"posicao": "pos_dir",    "pos_label": "Direita",   "rotacao": 90,  "face": "Face 2 (Lateral Dir.)"},
    11: {"posicao": "pos_dir",    "pos_label": "Direita",   "rotacao": 180, "face": "Face 3 (Traseira)"},
    12: {"posicao": "pos_dir",    "pos_label": "Direita",   "rotacao": 270, "face": "Face 4 (Lateral Esq.)"},

    # Bloco 4: Deslocado para a Frente (~15 cm)
    13: {"posicao": "pos_frente", "pos_label": "Frente",    "rotacao": 0,   "face": "Face 1 (Frontal)"},
    14: {"posicao": "pos_frente", "pos_label": "Frente",    "rotacao": 90,  "face": "Face 2 (Lateral Dir.)"},
    15: {"posicao": "pos_frente", "pos_label": "Frente",    "rotacao": 180, "face": "Face 3 (Traseira)"},
    16: {"posicao": "pos_frente", "pos_label": "Frente",    "rotacao": 270, "face": "Face 4 (Lateral Esq.)"},
}

# Tags padrão cadastradas do Experimento 7
DEFAULT_SENSING_EPC = "E2806995000050136FD0B575"
DEFAULT_REF_EPC     = "E2806995000050136FD0B975"

# Armazenamento em memória das tags escaneadas
scanned_tags: Dict[str, dict] = {}


# ===================================================================================
# Simulação Virtual (Mock) para Testes Offline do Experimento 7
# ===================================================================================

class MockReaderForExp7:
    """
    Simulador físico para testes offline do Experimento 7 sob umidade constante:
    - Umidade do solo fixada.
    - Perturbações espaciais e rotacionais introduzem perdas de propagação e descasamento
      angular que afetam ambas as tags de forma comum.
    - O DMRT (MRT_sens - MRT_ref) demonstra o cancelamento dessas perturbações.
    """
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200,
                 sensing_epc: str = DEFAULT_SENSING_EPC, ref_epc: str = DEFAULT_REF_EPC,
                 moisture_pct: float = 48.0, rotation_deg: int = 0, position: str = "pos_centro"):
        self.port = port
        self.baudrate = baudrate
        self.sensing_epc = sensing_epc.upper()
        self.ref_epc = ref_epc.upper()
        self.moisture_pct = moisture_pct
        self.rotation_deg = rotation_deg
        self.position = position
        self.power = 26.0
        self.is_reading = False

    def connect(self) -> bool:
        print(f"⚡ [MODO SIMULADO EXP7] Conectado virtualmente em {self.port}")
        return True

    def get_module_info(self) -> str:
        return "IN-R200 M100 V1.0 (SIMULADO EXP7)"

    def set_rf_power(self, power_dbm: float = 26.0, delay: float = 0.0) -> bool:
        self.power = power_dbm
        return True

    def _get_thresholds(self) -> Tuple[float, float]:
        """Calcula limiares simulados de MRT com perturbações espacial e angular comuns."""
        # Desvio angular pela rotação da tag/antena
        rot_offsets = {0: 0.0, 90: 0.8, 180: -0.4, 270: 0.5}
        rot_offset = rot_offsets.get(self.rotation_deg, 0.0)

        # Desvio espacial por posição na bancada (path loss / descentralização)
        pos_offsets = {
            "pos_centro": 0.0,
            "pos_esq": 1.2,
            "pos_dir": 1.0,
            "pos_frente": 0.8
        }
        pos_offset = pos_offsets.get(self.position, 1.0)

        # Referência: ~16.0 dBm no centro + perturbação angular e espacial
        ref_threshold = round(16.0 + rot_offset + pos_offset + random.uniform(-0.15, 0.15), 1)

        # Sensoriamento: ~18.5 dBm no centro (função da umidade de ~48%) + perturbações idênticas
        base_sens = 15.0 + (self.moisture_pct - 20.0) * 0.12
        sens_threshold = round(base_sens + rot_offset + pos_offset + random.uniform(-0.15, 0.15), 1)

        sens_threshold = max(15.0, min(26.0, sens_threshold))
        ref_threshold = max(15.0, min(26.0, ref_threshold))
        return sens_threshold, ref_threshold

    def read_multi_tag(self, loop_count: int = 3, timeout: float = 0.15,
                       target_epc: Optional[str] = None) -> Dict[str, dict]:
        detected = {}
        sens_thresh, ref_thresh = self._get_thresholds()

        if self.power >= sens_thresh:
            if target_epc is None or target_epc.upper() == self.sensing_epc:
                rssi = int(-70 + (self.power - sens_thresh) * 1.5 + random.uniform(-1, 1))
                detected[self.sensing_epc] = {"rssi": rssi, "pc": "3400", "count": loop_count}

        if self.power >= ref_thresh:
            if target_epc is None or target_epc.upper() == self.ref_epc:
                rssi = int(-68 + (self.power - ref_thresh) * 1.5 + random.uniform(-1, 1))
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
# Resolução de Tags e Histórico de Umidade
# ===================================================================================

def is_valid_hex_epc(epc: Optional[str]) -> bool:
    """Verifica se a string é um código EPC hexadecimal válido (24 caracteres)."""
    if not epc:
        return False
    clean = epc.strip()
    return len(clean) == 24 and all(c in "0123456789ABCDEFabcdef" for c in clean)


def load_tags_from_markdown(md_path: str = DEFAULT_MD_FILE) -> Tuple[Optional[str], Optional[str]]:
    """Carrega as tags do Experimento 7 do arquivo markdown de documentação."""
    if not os.path.exists(md_path):
        return None, None
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        m_sens = re.search(r"Tag.*?(?:Sensoriamento|Alvo|Sensing)\s*[:=]\s*`?([0-9A-Fa-f]{24})`?", content, re.IGNORECASE)
        m_ref = re.search(r"Tag.*?Refer[eê]ncia\s*[:=]\s*`?([0-9A-Fa-f]{24})`?", content, re.IGNORECASE)

        sens = m_sens.group(1).strip().upper() if m_sens else None
        ref = m_ref.group(1).strip().upper() if m_ref else None
        return sens, ref
    except Exception as e:
        print(f"⚠️ Aviso ao ler {md_path}: {e}")
        return None, None


def load_tags_from_json(json_path: str = DEFAULT_JSON_FILE) -> Tuple[Optional[str], Optional[str]]:
    """Carrega as tags cadastradas do Experimento 7 a partir do arquivo JSON."""
    if not os.path.exists(json_path):
        return None, None
    try:
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 1. Verifica na lista de pares
        for pair in data.get("pares", []):
            if "7" in str(pair.get("experimento", "")):
                return pair.get("sensoriamento"), pair.get("referencia")

        # 2. Verifica nas tags individuais associadas ao setup 7
        sens, ref = None, None
        for epc, info in data.get("tags", {}).items():
            setup_str = str(info.get("setup", ""))
            nome_str = str(info.get("nome", "")).lower()
            if setup_str == "7" or "exp-7" in nome_str or "exp 7" in nome_str:
                if info.get("funcao") == "sensoriamento" and not sens:
                    sens = epc
                elif info.get("funcao") == "referencia" and not ref:
                    ref = epc
        return sens, ref
    except Exception as e:
        print(f"⚠️ Erro ao ler tags do JSON {json_path}: {e}")
        return None, None


def resolve_tags(args, reader: Optional[INR200Reader] = None) -> Tuple[str, str]:
    """Resolve os EPCs prioritariamente por CLI, markdown ou JSON."""
    arg_tag = args.tag.strip().upper() if args.tag else None
    arg_ref = args.ref.strip().upper() if args.ref else None

    md_tag, md_ref = load_tags_from_markdown(args.md)
    json_tag, json_ref = load_tags_from_json(DEFAULT_JSON_FILE)

    sensing_epc = arg_tag or md_tag or json_tag or DEFAULT_SENSING_EPC
    ref_epc = arg_ref or md_ref or json_ref or DEFAULT_REF_EPC

    if is_valid_hex_epc(sensing_epc) and is_valid_hex_epc(ref_epc):
        return sensing_epc, ref_epc

    print(f"⚠️ Usando tags padrão do Experimento 7: {DEFAULT_SENSING_EPC} / {DEFAULT_REF_EPC}")
    return DEFAULT_SENSING_EPC, DEFAULT_REF_EPC


def get_last_recorded_moisture(csv_path: str = CONSOLIDATED_CSV) -> Optional[float]:
    """Recupera o último valor de umidade registrado no arquivo consolidado."""
    if not os.path.exists(csv_path):
        return None
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            if reader:
                last_row = reader[-1]
                val = float(last_row.get("umidade_pct", 0.0))
                if val > 0:
                    return val
    except Exception:
        pass
    return None


# ===================================================================================
# Exibição Formatada de Status e Tabelas no Terminal
# ===================================================================================

def is_tag_active(epc: str, current_time: float) -> bool:
    """Retorna True se a tag foi detectada recentemente."""
    if epc not in scanned_tags:
        return False
    return (current_time - scanned_tags[epc]["last_seen"]) <= TAG_TIMEOUT


def print_table(
    reading_counter: int,
    target_readings: int,
    bateria_num: Optional[int],
    moisture_pct: float,
    rotation_deg: int,
    position_name: str,
    sensing_epc: str,
    reference_epc: str,
    sens_hist_raw: List[float],
    sens_hist_filt: List[float],
    sens_hist_rssi: List[float],
    ref_hist_raw: List[float],
    ref_hist_filt: List[float],
    ref_hist_rssi: List[float],
    dmrt_hist: List[float],
    current_time: float
):
    """Exibe tabela no terminal com métricas completas ao vivo e acumuladas."""
    pct = (reading_counter / target_readings) * 100.0

    s_mean_filt = sum(sens_hist_filt) / len(sens_hist_filt) if sens_hist_filt else 0.0
    s_mean_raw  = sum(sens_hist_raw) / len(sens_hist_raw) if sens_hist_raw else 0.0
    s_mean_rssi = sum(sens_hist_rssi) / len(sens_hist_rssi) if sens_hist_rssi else 0.0

    r_mean_filt = sum(ref_hist_filt) / len(ref_hist_filt) if ref_hist_filt else 0.0
    r_mean_raw  = sum(ref_hist_raw) / len(ref_hist_raw) if ref_hist_raw else 0.0
    r_mean_rssi = sum(ref_hist_rssi) / len(ref_hist_rssi) if ref_hist_rssi else 0.0

    dmrt_mean = sum(dmrt_hist) / len(dmrt_hist) if dmrt_hist else 0.0

    bat_label = f"BATERIA {bateria_num:02d}/16" if bateria_num else f"LOCAL: {position_name.upper()}"
    header = f" EXPERIMENTO 7 | {bat_label} | POS: {position_name} | ROTAÇÃO: {rotation_deg}° | UMID: {moisture_pct:.1f}% | Varredura {reading_counter:04d}/{target_readings:04d} ({pct:.1f}%)"
    divider = "+" + "-" * 15 + "+" + "-" * 12 + "+" + "-" * 26 + "+" + "-" * 11 + "+" + "-" * 12 + "+" + "-" * 13 + "+" + "-" * 15 + "+"

    print("\n" + "=" * 113)
    print(f"{header:<113}")
    print("=" * 113)
    print(divider)
    print(f"| {'Condição':<13} | {'Função':<10} | {'Código EPC':<24} | {'RSSI':<9} | {'Raw MRT':<10} | {'Filt. MRT':<11} | {'MRT Médio Acum':<13} |")
    print(divider)

    # Linha da Tag de Sensoriamento
    if is_tag_active(sensing_epc, current_time):
        s_info = scanned_tags[sensing_epc]
        s_rssi_str = f"{s_info['rssi']} dBm" if s_info['rssi'] < 0 else f"-{s_info['rssi']} dBm"
        s_raw_str  = f"{s_info['raw_mrt']:.1f} dBm"
        s_filt_str = f"{s_info['filtered_mrt']:.2f} dBm"
    else:
        s_rssi_str, s_raw_str, s_filt_str = "Not seen", "N/A", "N/A"

    cond_str = f"{position_name[:5]} R{rotation_deg}°"
    print(f"| {cond_str:<13} | {'Sensor':<10} | {sensing_epc:<24} | {s_rssi_str:<9} | {s_raw_str:<10} | {s_filt_str:<11} | {s_mean_filt:11.2f} dBm |")

    # Linha da Tag de Referência
    if is_tag_active(reference_epc, current_time):
        r_info = scanned_tags[reference_epc]
        r_rssi_str = f"{r_info['rssi']} dBm" if r_info['rssi'] < 0 else f"-{r_info['rssi']} dBm"
        r_raw_str  = f"{r_info['raw_mrt']:.1f} dBm"
        r_filt_str = f"{r_info['filtered_mrt']:.2f} dBm"
    else:
        r_rssi_str, r_raw_str, r_filt_str = "Not seen", "N/A", "N/A"

    print(f"| {'':<13} | {'Referência':<10} | {reference_epc:<24} | {r_rssi_str:<9} | {r_raw_str:<10} | {r_filt_str:<11} | {r_mean_filt:11.2f} dBm |")
    print(divider)

    # Linha Diferencial DMRT
    dmrt_inst = None
    if is_tag_active(sensing_epc, current_time) and is_tag_active(reference_epc, current_time):
        dmrt_inst = scanned_tags[sensing_epc]["filtered_mrt"] - scanned_tags[reference_epc]["filtered_mrt"]
    dmrt_inst_str = f"{dmrt_inst:+.2f} dB" if dmrt_inst is not None else "N/A"
    dmrt_mean_str = f"{dmrt_mean:+.2f} dB" if dmrt_hist else "N/A"

    s_rssi_mean_str = f"{s_mean_rssi:.1f} dBm" if s_mean_rssi < 0 else f"-{s_mean_rssi:.1f} dBm"
    r_rssi_mean_str = f"{r_mean_rssi:.1f} dBm" if r_mean_rssi < 0 else f"-{r_mean_rssi:.1f} dBm"

    print(f" ⚖️  DMRT (Sens - Ref) : Instantâneo = {dmrt_inst_str}  |  Médio Acumulado = {dmrt_mean_str}")
    print(f" 📊 Médias Acumuladas  : Sensor MRT = {s_mean_filt:.2f} dBm (RSSI: {s_rssi_mean_str}) | Ref MRT = {r_mean_filt:.2f} dBm (RSSI: {r_rssi_mean_str})")


def show_experiment_status():
    """Exibe o status consolidado de todas as 16 baterias do catálogo."""
    print("\n" + "=" * 116)
    print("               STATUS DO EXPERIMENTO 7: INVARIÂNCIA ESPACIAL E ANGULAR SOB UMIDADE FIXA")
    print("=" * 116)
    print(f"| {'Bat':<3} | {'Posição Espacial':<18} | {'Rot (°)':<7} | {'Orientação Tag':<21} | {'Leituras':<8} | {'DMRT Médio':<11} | {'MRT Sensor':<11} | {'Status':<11} |")
    print("+" + "-" * 5 + "+" + "-" * 20 + "+" + "-" * 9 + "+" + "-" * 23 + "+" + "-" * 10 + "+" + "-" * 13 + "+" + "-" * 13 + "+" + "-" * 13 + "+")

    completed: Dict[str, dict] = {}
    if os.path.exists(CONSOLIDATED_CSV):
        try:
            with open(CONSOLIDATED_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = row.get("bateria", "").strip()
                    if key:
                        completed[key] = row
                    # chave secundária por posicao_rotacao
                    p = row.get("posicao", "")
                    r = row.get("rotacao_deg", "")
                    completed[f"{p}_{r}"] = row
        except Exception as e:
            print(f"⚠️ Erro ao ler consolidado: {e}")

    concluidas_count = 0
    for b in range(1, 17):
        cfg = BATERIAS_CONFIG[b]
        b_key = str(b)
        pr_key = f"{cfg['posicao']}_{cfg['rotacao']}"

        r = completed.get(b_key) or completed.get(pr_key)

        if r:
            concluidas_count += 1
            leits = f"{r.get('leituras_detectadas_dmrt', r.get('leituras_executadas', '0'))}/{r['leituras_planejadas']}"
            dmrt_str = f"{float(r['dmrt_medio']):+.2f} dB" if r.get('dmrt_medio') not in (None, 'N/A', '') else "N/A"
            mrt_sens = f"{float(r['sensing_mrt_filt_medio']):.2f} dBm" if r.get('sensing_mrt_filt_medio') not in (None, 'N/A', '') else "N/A"
            status = "✅ Concluída"
        else:
            leits = f"0/{DEFAULT_TARGET_READINGS}"
            dmrt_str = "-"
            mrt_sens = "-"
            status = "⏳ Pendente"

        pos_str = f"{cfg['pos_label']} ({cfg['posicao']})"
        print(f"| {b:02d}  | {pos_str:<18} | {cfg['rotacao']:>3}°   | {cfg['face']:<21} | {leits:<8} | {dmrt_str:<11} | {mrt_sens:<11} | {status:<11} |")

    print("+" + "-" * 5 + "+" + "-" * 20 + "+" + "-" * 9 + "+" + "-" * 23 + "+" + "-" * 10 + "+" + "-" * 13 + "+" + "-" * 13 + "+" + "-" * 13 + "+")
    pct_concluido = (concluidas_count / 16) * 100.0
    print(f"Total concluídas: {concluidas_count} de 16 baterias ({pct_concluido:.1f}%)")
    print("=" * 116 + "\n")


# ===================================================================================
# Consolidação de Dados e Gráficos Analíticos
# ===================================================================================

def calculate_stats(values: List[float]) -> Tuple[float, float, float, float]:
    """Calcula (média, desvio_padrão, mínimo, máximo)."""
    if not values:
        return 0.0, 0.0, 0.0, 0.0
    n = len(values)
    mean_val = sum(values) / n
    variance = sum((x - mean_val) ** 2 for x in values) / n if n > 1 else 0.0
    std_val = math.sqrt(variance)
    return mean_val, std_val, min(values), max(values)


def update_consolidated_csv(csv_path: str, record_dict: dict, key_field: str = "bateria"):
    """Atualiza ou insere registro na tabela CSV consolidada mantendo ordenação."""
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    rows_by_key = {}

    if os.path.exists(csv_path):
        try:
            with open(csv_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        k = row[key_field]
                        rows_by_key[k] = row
                    except KeyError:
                        pass
        except Exception as e:
            print(f"⚠️ Erro ao ler CSV consolidado existente: {e}")

    k_new = str(record_dict[key_field])
    rows_by_key[k_new] = {k: str(v) if v is not None else "N/A" for k, v in record_dict.items()}

    fieldnames = list(record_dict.keys())
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for k in sorted(rows_by_key.keys(), key=lambda x: int(x) if x.isdigit() else x):
            writer.writerow(rows_by_key[k])

    print(f"📁 Tabela consolidada atualizada: {os.path.abspath(csv_path)}")


def generate_consolidated_charts():
    """Gera os gráficos analíticos demonstrando a invariância angular e espacial do DMRT."""
    if not os.path.exists(CONSOLIDATED_CSV):
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        records = []
        with open(CONSOLIDATED_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                records.append(r)

        if len(records) < 2:
            return  # Gera apenas com 2 ou mais baterias concluídas

        # ---------------------------------------------------------------------------
        # Gráfico 1: Rotação vs DMRT e MRT Bruto para cada Posição Espacial
        # ---------------------------------------------------------------------------
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), dpi=150)

        posicoes_unicas = sorted(list({r["posicao"] for r in records}))
        pos_colors = {
            "pos_centro": "#1f77b4",
            "pos_esq": "#ff7f0e",
            "pos_dir": "#2ca02c",
            "pos_frente": "#d62728"
        }
        pos_labels = {
            "pos_centro": "Centro",
            "pos_esq": "Esquerda (-15cm)",
            "pos_dir": "Direita (+15cm)",
            "pos_frente": "Frente (+15cm)"
        }

        for pos in posicoes_unicas:
            sub = [r for r in records if r["posicao"] == pos]
            sub = sorted(sub, key=lambda x: int(x["rotacao_deg"]))

            c = pos_colors.get(pos, "#9467bd")
            lbl = pos_labels.get(pos, pos)

            # Extrai pontos validos para DMRT
            valid_dmrt_pts = [
                (int(x["rotacao_deg"]), float(x["dmrt_medio"]), float(x["dmrt_std"]))
                for x in sub
                if x.get("dmrt_medio") not in ("N/A", "", None) and float(x.get("leituras_detectadas_dmrt", 0)) > 0
            ]
            if valid_dmrt_pts:
                rot_d, d_val, d_std = zip(*valid_dmrt_pts)
                ax1.errorbar(
                    rot_d, d_val, yerr=d_std, fmt='-o',
                    color=c, linewidth=2, markersize=7, capsize=4,
                    label=f"DMRT: {lbl}"
                )

            # Extrai pontos validos para MRT Sensor
            valid_mrt_pts = [
                (int(x["rotacao_deg"]), float(x["sensing_mrt_filt_medio"]))
                for x in sub
                if float(x.get("sensing_mrt_filt_medio", 0)) > 0
            ]
            if valid_mrt_pts:
                rot_m, m_val = zip(*valid_mrt_pts)
                ax2.plot(
                    rot_m, m_val, '--s',
                    color=c, linewidth=1.8, markersize=6,
                    label=f"MRT Sensor: {lbl}"
                )

        ax1.set_title("Estabilidade do DMRT pelas Rotações (Invariância Diferencial)", fontsize=11, fontweight="bold")
        ax1.set_xlabel("Ângulo de Rotação do Vaso (Graus)", fontsize=10)
        ax1.set_ylabel("DMRT Médio: MRT_sens - MRT_ref (dB)", fontsize=10)
        ax1.set_xticks([0, 90, 180, 270])
        ax1.grid(True, linestyle="--", alpha=0.5)
        ax1.legend(loc="best", fontsize=9)

        ax2.set_title("Flutuações do MRT Absoluto da Tag de Sensoriamento", fontsize=11, fontweight="bold")
        ax2.set_xlabel("Ângulo de Rotação do Vaso (Graus)", fontsize=10)
        ax2.set_ylabel("MRT Filtrado Médio da Tag de Sensoriamento (dBm)", fontsize=10)
        ax2.set_xticks([0, 90, 180, 270])
        ax2.grid(True, linestyle="--", alpha=0.5)
        ax2.legend(loc="best", fontsize=9)

        u_val = float(records[0].get("umidade_pct", 70.0))
        fig.suptitle(f"Experimento 7: Impacto da Rotação e Posição sob Umidade Fixa ({u_val:.1f}%)\nDemonstração de Invariância do DMRT vs Sensibilidade do MRT Bruto", fontsize=12, fontweight="bold")
        fig.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(CHART_ROTATION_DMRT)), exist_ok=True)
        plt.savefig(CHART_ROTATION_DMRT, format="png", bbox_inches="tight")
        plt.close()
        print(f"📈 Gráfico Rotação vs DMRT gerado: {os.path.abspath(CHART_ROTATION_DMRT)}")

        # ---------------------------------------------------------------------------
        # Gráfico 2: Comparativo Espacial (Por Posição na Bancada)
        # ---------------------------------------------------------------------------
        fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
        pos_labels_list = []
        dmrt_by_pos = []
        sens_by_pos = []
        rssi_by_pos = []

        for pos in posicoes_unicas:
            sub = [r for r in records if r["posicao"] == pos]
            p_lbl = pos_labels.get(pos, pos)
            pos_labels_list.append(p_lbl)

            valid_dmrt = [float(x["dmrt_medio"]) for x in sub if x.get("dmrt_medio") not in ("N/A", "", None) and float(x.get("leituras_detectadas_dmrt", 0)) > 0]
            valid_sens = [float(x["sensing_mrt_filt_medio"]) for x in sub if float(x.get("sensing_mrt_filt_medio", 0)) > 0]
            valid_rssi = [float(x["sensing_rssi_medio"]) for x in sub if float(x.get("sensing_rssi_medio", 0)) < 0]

            dmrt_by_pos.append(sum(valid_dmrt) / len(valid_dmrt) if valid_dmrt else 0.0)
            sens_by_pos.append(sum(valid_sens) / len(valid_sens) if valid_sens else 0.0)
            rssi_by_pos.append(sum(valid_rssi) / len(valid_rssi) if valid_rssi else 0.0)

        x_indices = range(len(posicoes_unicas))
        width = 0.25

        ax.bar([i - width for i in x_indices], dmrt_by_pos, width, label="DMRT Médio (dB)", color="#2ca02c")
        ax.bar([i for i in x_indices], sens_by_pos, width, label="MRT Sensor Médio (dBm)", color="#1f77b4")
        ax.bar([i + width for i in x_indices], [abs(r) for r in rssi_by_pos], width, label="|RSSI| Sensor Médio (dBm)", color="#ff7f0e")

        ax.set_xticks(list(x_indices))
        ax.set_xticklabels(pos_labels_list, fontsize=10, fontweight="bold")
        ax.set_ylabel("Magnitude (dB / dBm)", fontsize=10)
        ax.set_title("Comparativo Espacial: Robustez do DMRT vs Flutuações de MRT e RSSI", fontsize=11, fontweight="bold")
        ax.grid(True, linestyle="--", alpha=0.4, axis="y")
        ax.legend(loc="upper right", fontsize=9)

        fig.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(CHART_SPATIAL_DMRT)), exist_ok=True)
        plt.savefig(CHART_SPATIAL_DMRT, format="png", bbox_inches="tight")
        plt.close()
        print(f"📈 Gráfico Espacial vs Métricas gerado: {os.path.abspath(CHART_SPATIAL_DMRT)}")

    except Exception as e:
        print(f"⚠️ Não foi possível gerar gráficos consolidados: {e}")


# ===================================================================================
# Pipeline Principal de Execução
# ===================================================================================

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Experimento 7: Invariância Espacial e Angular do DMRT sob Umidade Fixa do Solo"
    )
    parser.add_argument(
        "--bateria", type=int, choices=list(range(1, 17)), default=None,
        help="Número da bateria do catálogo (1 a 16). Define posição espacial e ângulo de rotação automaticamente."
    )
    parser.add_argument(
        "--posicao", type=str, default=None,
        help="Localização espacial do vaso na bancada (ex: pos_centro, pos_esq, pos_dir, pos_frente, etc.)"
    )
    parser.add_argument(
        "--rotacao", type=int, choices=[0, 90, 180, 270], default=None,
        help="Ângulo de rotação da tag / vaso em graus (0, 90, 180, 270)"
    )
    parser.add_argument(
        "--umidade", type=float, default=None,
        help="Umidade fixa do solo medida pelo sensor RainPoint (ex: 48.0%%). Se omitida, usa o último valor gravado."
    )
    parser.add_argument(
        "--readings", type=int, default=DEFAULT_TARGET_READINGS,
        help=f"Quantidade de varreduras por bateria (padrão: {DEFAULT_TARGET_READINGS})"
    )
    parser.add_argument(
        "--dwell", type=float, default=0.12,
        help="Tempo de permanência RF em segundos por nível (padrão: 0.12s para varredura rápida)"
    )
    parser.add_argument(
        "--power-step", type=float, default=1.0,
        help="Passo de incremento de potência em dBm (padrão: 1.0 dBm)"
    )
    parser.add_argument(
        "--min-power", type=float, default=15.0,
        help="Potência mínima em dBm (padrão: 15.0 dBm)"
    )
    parser.add_argument(
        "--max-power", type=float, default=26.0,
        help="Potência máxima em dBm (padrão: 26.0 dBm)"
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
        "--md", default=DEFAULT_MD_FILE,
        help=f"Arquivo markdown do experimento (padrão: {DEFAULT_MD_FILE})"
    )
    parser.add_argument(
        "--tag", default=None,
        help="EPC da Tag de Sensoriamento (24 caracteres hex)"
    )
    parser.add_argument(
        "--ref", default=None,
        help="EPC da Tag de Referência (24 caracteres hex)"
    )
    parser.add_argument(
        "--simulado", action="store_true",
        help="Executa em modo simulador sem hardware físico do leitor"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Exibe a tabela consolidada das baterias e encerra"
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    # Se o usuário solicitou apenas visualização de status
    if args.status:
        show_experiment_status()
        return

    # 1. Determina Configuração da Rodada Atual
    bateria_num = args.bateria

    if bateria_num is not None:
        cfg = BATERIAS_CONFIG[bateria_num]
        posicao = cfg["posicao"]
        rotacao_deg = cfg["rotacao"]
        face_nome = cfg["face"]
        pos_label = cfg["pos_label"]
        slug = f"bateria_{bateria_num:02d}_{posicao}_rot_{rotacao_deg}deg"
    else:
        posicao = args.posicao or "pos_centro"
        rotacao_deg = args.rotacao if args.rotacao is not None else 0
        face_nome = f"Rotação {rotacao_deg}°"
        pos_label = posicao
        slug = f"ensaio_{posicao}_rot_{rotacao_deg}deg"

    # Determina umidade do solo fixa
    if args.umidade is not None:
        umidade_pct = args.umidade
    else:
        last_u = get_last_recorded_moisture()
        umidade_pct = last_u if last_u is not None else 48.0

    csv_path = os.path.join(EXP7_DIR, f"{slug}_resultados.csv")
    chart_path = os.path.join(EXP7_DIR, f"{slug}_grafico.png")
    setup_title = f"Experimento 7: {slug.upper()} (Pos: {posicao}, Rot: {rotacao_deg}°, Umid: {umidade_pct:.1f}%)"

    # 2. Conecta ao Leitor (ou Instancia Mock)
    reader = None
    if not args.simulado:
        reader = INR200Reader(port=args.port, baudrate=args.baudrate)
        if not reader.connect():
            print(f"\n❌ Não foi possível conectar ao leitor na porta {args.port}.")
            print(f"👉 Conceda permissão: sudo chmod 666 {args.port}")
            print("👉 Ou execute com flag --simulado para testar offline.")
            sys.exit(1)

    # 3. Resolve Tags Mapeadas
    sensing_epc, ref_epc = resolve_tags(args, reader=reader)

    if args.simulado:
        reader = MockReaderForExp7(
            port=args.port,
            baudrate=args.baudrate,
            sensing_epc=sensing_epc,
            ref_epc=ref_epc,
            moisture_pct=umidade_pct,
            rotation_deg=rotacao_deg,
            position=posicao
        )
        reader.connect()

    target_readings = args.readings

    # 4. Banner Informativo do Setup
    print("=" * 112)
    print("      IN-R200 UHF RFID Reader - EXPERIMENTO 7: INVARIÂNCIA ESPACIAL E ANGULAR (DMRT/MRT/RSSI)")
    print("=" * 112)
    if bateria_num:
        print(f"📦 Bateria             : {bateria_num:02d} de 16 ({pos_label} | {face_nome})")
    print(f"📍 Localização Espacial: {posicao} ({pos_label})")
    print(f"🔄 Rotação do Vaso      : {rotacao_deg}° ({face_nome})")
    print(f"💧 Umidade do Solo Fixa : {umidade_pct:.1f}% (Sensor RainPoint)")
    print(f"🏷️  Tag Sensoriamento    : {sensing_epc} (Vaso de solo)")
    print(f"🏷️  Tag Referência       : {ref_epc} (Isolada de referência)")
    print(f"⚡ Faixa de Potência    : {args.min_power:.1f} dBm a {args.max_power:.1f} dBm (passo {args.power_step} dBm com early-stop)")
    print(f"⏱️  Tempo Dwell/Nível   : {args.dwell:.3f} s")
    print(f"🎯 Meta de Leituras     : {target_readings} varreduras completas")
    print(f"📁 Arquivo CSV          : {csv_path}")
    print(f"📈 Gráfico PNG          : {chart_path}")
    print("=" * 112)

    # 5. Inicializa Calculadora MRT e Exportador DMRT
    mrt_calc = MRTCalculator(
        reader=reader,
        min_power=args.min_power,
        max_power=args.max_power,
        power_step=args.power_step,
        dwell_time=args.dwell
    )
    exporter = DMRTExporter()
    target_list = [sensing_epc, ref_epc]

    # Históricos de métricas para estatísticas
    sens_hist_raw: List[float] = []
    sens_hist_filt: List[float] = []
    sens_hist_rssi: List[float] = []

    ref_hist_raw: List[float] = []
    ref_hist_filt: List[float] = []
    ref_hist_rssi: List[float] = []

    dmrt_hist: List[float] = []

    print(f"\n📡 Iniciando as {target_readings} leituras com parada antecipada otimizada...")
    print("   (Pressione Ctrl+C a qualquer momento para finalizar e salvar os dados parciais)\n")

    reading_counter = 0

    try:
        while reading_counter < target_readings:
            reading_counter += 1
            t_sweep_0 = time.time()

            # Varredura linear com parada antecipada assim que AMBAS as tags responderem
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
                    scanned_tags[epc] = {
                        "count": info["count"],
                        "rssi": info["rssi"],
                        "pc": info["pc"],
                        "raw_mrt": raw_mrt,
                        "filtered_mrt": filt_mrt,
                        "first_seen": now,
                        "last_seen": now
                    }
                else:
                    scanned_tags[epc]["count"] += info["count"]
                    scanned_tags[epc]["rssi"] = info["rssi"]
                    scanned_tags[epc]["pc"] = info["pc"]
                    scanned_tags[epc]["raw_mrt"] = raw_mrt
                    scanned_tags[epc]["filtered_mrt"] = filt_mrt
                    scanned_tags[epc]["last_seen"] = now

            current_time = time.time()
            s_seen = sensing_epc in scan_results
            r_seen = ref_epc in scan_results

            s_data = scanned_tags.get(sensing_epc) if s_seen else None
            r_data = scanned_tags.get(ref_epc) if r_seen else None

            # Registra histórico
            if s_data:
                sens_hist_raw.append(s_data["raw_mrt"])
                sens_hist_filt.append(s_data["filtered_mrt"])
                sens_hist_rssi.append(s_data["rssi"])

            if r_data:
                ref_hist_raw.append(r_data["raw_mrt"])
                ref_hist_filt.append(r_data["filtered_mrt"])
                ref_hist_rssi.append(r_data["rssi"])

            # Cálculo de DMRT
            dmrt_val = None
            if s_data and r_data:
                dmrt_val = MRTCalculator.calculate_dmrt(
                    s_data["filtered_mrt"],
                    r_data["filtered_mrt"]
                )
                dmrt_hist.append(dmrt_val)

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
                moisture_pct=umidade_pct,
                rotation_deg=float(rotacao_deg),
                position=posicao
            )

            # Log resumido por linha
            s_str = f"S:{s_data['filtered_mrt']:.1f}dBm" if s_data else "S:MISS"
            r_str = f"R:{r_data['filtered_mrt']:.1f}dBm" if r_data else "R:MISS"
            d_str = f"DMRT:{dmrt_val:+.2f}dB" if dmrt_val is not None else "DMRT:N/A"
            print(f"  ⚡ [{reading_counter:04d}/{target_readings}] {s_str} | {r_str} | {d_str} | Tempo: {dt_sweep:.2f}s")

            # Tabela periódica
            if reading_counter % 10 == 0 or reading_counter == target_readings:
                print_table(
                    reading_counter, target_readings, bateria_num,
                    umidade_pct, rotacao_deg, posicao, sensing_epc, ref_epc,
                    sens_hist_raw, sens_hist_filt, sens_hist_rssi,
                    ref_hist_raw, ref_hist_filt, ref_hist_rssi,
                    dmrt_hist, current_time
                )

    except KeyboardInterrupt:
        print("\n\n⏹️ Coleta interrompida pelo usuário via Ctrl+C.")
    finally:
        # Encerra conexão com o leitor
        reader.set_rf_power(26.0)
        reader.close()

        os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)

        # Exporta CSV e Gráfico da rodada
        print(f"\n📊 Exportando resultados para {csv_path}...")
        exporter.export_experiment_chart(
            chart_filename=chart_path,
            csv_filename=csv_path,
            title_prefix=setup_title
        )

        # Estatísticas finais
        s_raw_mean, s_raw_std, _, _ = calculate_stats(sens_hist_raw)
        s_filt_mean, s_filt_std, _, _ = calculate_stats(sens_hist_filt)
        s_rssi_mean, s_rssi_std, _, _ = calculate_stats(sens_hist_rssi)

        r_raw_mean, r_raw_std, _, _ = calculate_stats(ref_hist_raw)
        r_filt_mean, r_filt_std, _, _ = calculate_stats(ref_hist_filt)
        r_rssi_mean, r_rssi_std, _, _ = calculate_stats(ref_hist_rssi)

        dmrt_mean, dmrt_std, _, _ = calculate_stats(dmrt_hist)

        # Registro para tabela consolidada
        key_val = str(bateria_num) if bateria_num else f"{posicao}_r{rotacao_deg}"
        record_entry = {
            "bateria": key_val,
            "posicao": posicao,
            "rotacao_deg": rotacao_deg,
            "umidade_pct": f"{umidade_pct:.1f}",
            "leituras_planejadas": target_readings,
            "leituras_executadas": reading_counter,
            "leituras_detectadas_sens": len(sens_hist_filt),
            "leituras_detectadas_ref": len(ref_hist_filt),
            "leituras_detectadas_dmrt": len(dmrt_hist),
            "taxa_deteccao_dmrt_pct": f"{(len(dmrt_hist) / target_readings * 100.0):.1f}" if target_readings > 0 else "0.0",
            "sensing_mrt_raw_medio": f"{s_raw_mean:.2f}",
            "sensing_mrt_raw_std": f"{s_raw_std:.2f}",
            "sensing_mrt_filt_medio": f"{s_filt_mean:.2f}",
            "sensing_mrt_filt_std": f"{s_filt_std:.2f}",
            "ref_mrt_raw_medio": f"{r_raw_mean:.2f}",
            "ref_mrt_raw_std": f"{r_raw_std:.2f}",
            "ref_mrt_filt_medio": f"{r_filt_mean:.2f}",
            "ref_mrt_filt_std": f"{r_filt_std:.2f}",
            "dmrt_medio": f"{dmrt_mean:.2f}" if dmrt_hist else "N/A",
            "dmrt_std": f"{dmrt_std:.2f}" if dmrt_hist else "N/A",
            "sensing_rssi_medio": f"{s_rssi_mean:.1f}",
            "sensing_rssi_std": f"{s_rssi_std:.2f}",
            "ref_rssi_medio": f"{r_rssi_mean:.1f}",
            "ref_rssi_std": f"{r_rssi_std:.2f}",
            "sensing_epc": sensing_epc,
            "reference_epc": ref_epc,
            "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        update_consolidated_csv(CONSOLIDATED_CSV, record_entry, key_field="bateria")
        generate_consolidated_charts()

    # Relatório Final
    s_rssi_fmt = f"{s_rssi_mean:.1f} dBm" if s_rssi_mean < 0 else f"-{s_rssi_mean:.1f} dBm"
    r_rssi_fmt = f"{r_rssi_mean:.1f} dBm" if r_rssi_mean < 0 else f"-{r_rssi_mean:.1f} dBm"

    print("\n" + "=" * 112)
    print(f"        RELATÓRIO FINAL: {setup_title.upper()}")
    print("=" * 112)
    print(f"📌 Tag Sensoriamento : {sensing_epc} (Vaso de solo)")
    print(f"📌 Tag Referência    : {ref_epc} (Isolada de referência)")
    print(f"📍 Local / Posição   : {posicao}")
    print(f"🔄 Rotação do Vaso   : {rotacao_deg}° ({face_nome})")
    print(f"💧 Umidade Fixa Solo : {umidade_pct:.1f}%")
    print(f"🔢 Varreduras        : {reading_counter} realizadas ({len(dmrt_hist)} pares válidos com DMRT)")
    print("-" * 112)
    print(f"🎯 Sensor MRT (EMA)  : {s_filt_mean:.2f} dBm  (± {s_filt_std:.2f} dB) | RSSI: {s_rssi_fmt}")
    print(f"🎯 Referência MRT    : {r_filt_mean:.2f} dBm  (± {r_filt_std:.2f} dB) | RSSI: {r_rssi_fmt}")
    print(f"⚖️  DMRT Médio (ΔMRT): {dmrt_mean:+.2f} dB   (± {dmrt_std:.2f} dB)")
    print("-" * 112)
    print(f"👉 RESULTADO DA RODADA: DMRT = {dmrt_mean:+.2f} dB | Sensor MRT = {s_filt_mean:.2f} dBm")
    print("=" * 112)
    print(f"✅ CSV da rodada salvo em          : {os.path.abspath(csv_path)}")
    print(f"✅ Gráfico da rodada salvo em      : {os.path.abspath(chart_path)}")
    print(f"✅ Tabela consolidada salva em     : {os.path.abspath(CONSOLIDATED_CSV)}")
    if os.path.exists(CHART_ROTATION_DMRT):
        print(f"✅ Curva Rotação vs DMRT gerada em : {os.path.abspath(CHART_ROTATION_DMRT)}")
    if os.path.exists(CHART_SPATIAL_DMRT):
        print(f"✅ Curva Espacial vs DMRT gerada em: {os.path.abspath(CHART_SPATIAL_DMRT)}")
    print("=" * 112)


if __name__ == "__main__":
    main()
