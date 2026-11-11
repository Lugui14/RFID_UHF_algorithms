"""
===================================================================================
 Experimento 8: Resiliência Ambiental do DMRT em 6 Diferentes Localizações
 Métricas: DMRT, MRT (Sensoriamento e Referência) e RSSI sob Umidade Constante
===================================================================================
 Descrição:
 - Avalia a resiliência e invariância ambiental da métrica diferencial GreenTag
   (ACM TOSN 2025) posicionando o setup completo do experimento (antena + vaso
   com tags de sensoriamento e referência em geometria fixa) em 6 diferentes
   localizações físicas (diferentes ambientes/bancadas com distintos perfis de
   reflexão e multicaminho), mantendo a mesma umidade do solo.
 - Duas tags RFID UHF mapeadas:
     * Tag de Sensoriamento : E2806995000050136FD0B575 (no substrato do vaso)
     * Tag de Referência    : E2806995000050136FD0B975 (isolada no ar/referência)
 - Mede para cada uma das 6 localidades (300 medições por localidade):
     * MRT da Tag de Sensoriamento (bruto e filtrado EMA)
     * MRT da Tag de Referência (bruto e filtrado EMA)
     * DMRT (Limiar Mínimo Diferencial: MRT_sens - MRT_ref)
     * RSSI da Tag de Sensoriamento e da Tag de Referência
 - Ao final, consolida os dados e gera os gráficos de variação do DMRT nas 6
   localidades para comprovar a resiliência da métrica frente ao ambiente.
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

# Diretórios e caminhos padrão do Experimento 8
EXP8_DIR = "experimento_8"
DEFAULT_MD_FILE = os.path.join(EXP8_DIR, "experimento8.md")
DEFAULT_JSON_FILE = "tags_mapeadas.json"
CONSOLIDATED_CSV = os.path.join(EXP8_DIR, "consolidado_exp8.csv")
CHART_DMRT_LOCATIONS = os.path.join(EXP8_DIR, "variacao_dmrt_localidades.png")
CHART_METRICS_COMPARISON = os.path.join(EXP8_DIR, "comparativo_metricas_localidades.png")

DEFAULT_TARGET_READINGS = 300
TAG_TIMEOUT = 10.0

# -----------------------------------------------------------------------------------
# Catálogo das 6 Localizações do Experimento 8 (Mesma Umidade e Mesma Geometria Fixa)
# -----------------------------------------------------------------------------------
LOCALIDADES_CONFIG = {
    1: {"codigo": "local_01", "nome": "Localização 01", "descricao": "Ambiente / Ponto de Teste 1"},
    2: {"codigo": "local_02", "nome": "Localização 02", "descricao": "Ambiente / Ponto de Teste 2"},
    3: {"codigo": "local_03", "nome": "Localização 03", "descricao": "Ambiente / Ponto de Teste 3"},
    4: {"codigo": "local_04", "nome": "Localização 04", "descricao": "Ambiente / Ponto de Teste 4"},
    5: {"codigo": "local_05", "nome": "Localização 05", "descricao": "Ambiente / Ponto de Teste 5"},
    6: {"codigo": "local_06", "nome": "Localização 06", "descricao": "Ambiente / Ponto de Teste 6"},
}

# Tags padrão cadastradas para o Experimento 8
DEFAULT_SENSING_EPC = "E2806995000050136FD0B575"
DEFAULT_REF_EPC     = "E2806995000050136FD0B975"

# Armazenamento em memória das tags escaneadas
scanned_tags: Dict[str, dict] = {}


# ===================================================================================
# Simulação Virtual (Mock) para Testes Offline do Experimento 8
# ===================================================================================

class MockReaderForExp8:
    """
    Simulador físico para testes offline do Experimento 8 sob umidade constante:
    - Umidade do solo e geometria antena-vaso fixadas.
    - Cada uma das 6 localizações introduz diferentes reflexões ambientais (multicaminho)
      que deslocam os MRTs absolutos em modo comum, enquanto o DMRT permanece resiliente.
    """
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200,
                 sensing_epc: str = DEFAULT_SENSING_EPC, ref_epc: str = DEFAULT_REF_EPC,
                 moisture_pct: float = 48.0, local_num: int = 1):
        self.port = port
        self.baudrate = baudrate
        self.sensing_epc = sensing_epc.upper()
        self.ref_epc = ref_epc.upper()
        self.moisture_pct = moisture_pct
        self.local_num = local_num
        self.power = 26.0
        self.is_reading = False

    def connect(self) -> bool:
        print(f"⚡ [MODO SIMULADO EXP8] Conectado virtualmente em {self.port} (Localização {self.local_num})")
        return True

    def get_module_info(self) -> str:
        return "IN-R200 M100 V1.0 (SIMULADO EXP8)"

    def set_rf_power(self, power_dbm: float = 26.0, delay: float = 0.0) -> bool:
        self.power = power_dbm
        return True

    def _get_thresholds(self) -> Tuple[float, float]:
        """Calcula limiares simulados de MRT com perturbação ambiental comum por localidade."""
        env_offsets = {
            1: 0.0,
            2: 1.1,
            3: -0.5,
            4: 1.6,
            5: 0.7,
            6: 1.3
        }
        env_offset = env_offsets.get(self.local_num, 0.5)

        # Referência: ~15.5 dBm base + perturbação do ambiente (modo comum)
        ref_threshold = round(15.5 + env_offset + random.uniform(-0.15, 0.15), 1)

        # Sensoriamento: função da umidade fixa + mesma perturbação do ambiente
        base_sens = 15.5 + (self.moisture_pct - 20.0) * 0.12
        sens_threshold = round(base_sens + env_offset + random.uniform(-0.15, 0.15), 1)

        sens_threshold = max(15.0, min(26.0, sens_threshold))
        ref_threshold = max(15.0, min(26.0, ref_threshold))
        return sens_threshold, ref_threshold

    def read_multi_tag(self, loop_count: int = 3, timeout: float = 0.15,
                       target_epc: Optional[str] = None) -> Dict[str, dict]:
        detected = {}
        sens_thresh, ref_thresh = self._get_thresholds()

        if self.power >= sens_thresh:
            if target_epc is None or target_epc.upper() == self.sensing_epc:
                rssi = int(-71 + (self.power - sens_thresh) * 1.5 + random.uniform(-1, 1))
                detected[self.sensing_epc] = {"rssi": rssi, "pc": "3400", "count": loop_count}

        if self.power >= ref_thresh:
            if target_epc is None or target_epc.upper() == self.ref_epc:
                rssi = int(-58 + (self.power - ref_thresh) * 1.5 + random.uniform(-1, 1))
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
    """Carrega as tags do Experimento 8 do arquivo markdown de documentação."""
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
    """Carrega as tags cadastradas do Experimento 8 (ou 7) a partir do arquivo JSON."""
    if not os.path.exists(json_path):
        return None, None
    try:
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 1. Verifica na lista de pares (prioriza Experimento 8, fallback Experimento 7)
        for exp_id in ("8", "7"):
            for pair in data.get("pares", []):
                if exp_id in str(pair.get("experimento", "")):
                    return pair.get("sensoriamento"), pair.get("referencia")

        # 2. Verifica nas tags individuais associadas ao setup 8 ou 7
        sens, ref = None, None
        for epc, info in data.get("tags", {}).items():
            setup_str = str(info.get("setup", ""))
            nome_str = str(info.get("nome", "")).lower()
            if setup_str in ("8", "7") or "exp-8" in nome_str or "exp-7" in nome_str:
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

    print(f"⚠️ Usando tags padrão do Experimento 8: {DEFAULT_SENSING_EPC} / {DEFAULT_REF_EPC}")
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
    local_num: int,
    local_code: str,
    local_name: str,
    moisture_pct: float,
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
    s_mean_rssi = sum(sens_hist_rssi) / len(sens_hist_rssi) if sens_hist_rssi else 0.0

    r_mean_filt = sum(ref_hist_filt) / len(ref_hist_filt) if ref_hist_filt else 0.0
    r_mean_rssi = sum(ref_hist_rssi) / len(ref_hist_rssi) if ref_hist_rssi else 0.0

    dmrt_mean = sum(dmrt_hist) / len(dmrt_hist) if dmrt_hist else 0.0

    loc_label = f"LOCAL {local_num:02d}/06 ({local_name})"
    header = f" EXPERIMENTO 8 | {loc_label} | UMIDADE FIXA: {moisture_pct:.1f}% | Varredura {reading_counter:04d}/{target_readings:04d} ({pct:.1f}%)"
    divider = "+" + "-" * 15 + "+" + "-" * 12 + "+" + "-" * 26 + "+" + "-" * 11 + "+" + "-" * 12 + "+" + "-" * 13 + "+" + "-" * 15 + "+"

    print("\n" + "=" * 113)
    print(f"{header:<113}")
    print("=" * 113)
    print(divider)
    print(f"| {'Localidade':<13} | {'Função':<10} | {'Código EPC':<24} | {'RSSI':<9} | {'Raw MRT':<10} | {'Filt. MRT':<11} | {'MRT Médio Acum':<13} |")
    print(divider)

    # Linha da Tag de Sensoriamento
    if is_tag_active(sensing_epc, current_time):
        s_info = scanned_tags[sensing_epc]
        s_rssi_str = f"{s_info['rssi']} dBm" if s_info['rssi'] < 0 else f"-{s_info['rssi']} dBm"
        s_raw_str  = f"{s_info['raw_mrt']:.1f} dBm"
        s_filt_str = f"{s_info['filtered_mrt']:.2f} dBm"
    else:
        s_rssi_str, s_raw_str, s_filt_str = "Not seen", "N/A", "N/A"

    print(f"| {local_code:<13} | {'Sensor':<10} | {sensing_epc:<24} | {s_rssi_str:<9} | {s_raw_str:<10} | {s_filt_str:<11} | {s_mean_filt:11.2f} dBm |")

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
    """Exibe o status consolidado das 6 localizações do Experimento 8."""
    print("\n" + "=" * 120)
    print("          STATUS DO EXPERIMENTO 8: RESILIÊNCIA DO DMRT EM 6 DIFERENTES LOCALIZAÇÕES (UMIDADE FIXA)")
    print("=" * 120)
    print(f"| {'Loc':<3} | {'Código':<10} | {'Nome / Ambiente':<24} | {'Umid.':<6} | {'Leituras':<8} | {'DMRT Médio (±Std)':<18} | {'MRT Sensor':<11} | {'MRT Ref':<10} | {'Status':<11} |")
    print("+" + "-" * 5 + "+" + "-" * 12 + "+" + "-" * 26 + "+" + "-" * 8 + "+" + "-" * 10 + "+" + "-" * 20 + "+" + "-" * 13 + "+" + "-" * 12 + "+" + "-" * 13 + "+")

    completed: Dict[str, dict] = {}
    if os.path.exists(CONSOLIDATED_CSV):
        try:
            with open(CONSOLIDATED_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = row.get("local_num", "").strip()
                    if key:
                        completed[key] = row
                    code_key = row.get("local_codigo", "").strip()
                    if code_key:
                        completed[code_key] = row
        except Exception as e:
            print(f"⚠️ Erro ao ler consolidado: {e}")

    concluidas_count = 0
    dmrt_means = []
    sens_means = []
    ref_means = []

    for loc_num in range(1, 7):
        cfg = LOCALIDADES_CONFIG[loc_num]
        r = completed.get(str(loc_num)) or completed.get(cfg["codigo"])

        if r:
            concluidas_count += 1
            nome_exib = r.get("local_nome", cfg["nome"])[:24]
            umid_str = f"{float(r.get('umidade_pct', 0.0)):.1f}%"
            leits = f"{r.get('leituras_detectadas_dmrt', r.get('leituras_executadas', '0'))}/{r['leituras_planejadas']}"
            if r.get("dmrt_medio") not in (None, "N/A", ""):
                d_val = float(r["dmrt_medio"])
                d_std = float(r.get("dmrt_std", 0.0))
                dmrt_str = f"{d_val:+.2f} ± {d_std:.2f} dB"
                dmrt_means.append(d_val)
            else:
                dmrt_str = "N/A"

            if r.get("sensing_mrt_filt_medio") not in (None, "N/A", ""):
                s_val = float(r["sensing_mrt_filt_medio"])
                mrt_sens = f"{s_val:.2f} dBm"
                sens_means.append(s_val)
            else:
                mrt_sens = "N/A"

            if r.get("ref_mrt_filt_medio") not in (None, "N/A", ""):
                ref_val = float(r["ref_mrt_filt_medio"])
                mrt_ref = f"{ref_val:.2f} dBm"
                ref_means.append(ref_val)
            else:
                mrt_ref = "N/A"

            status = "✅ Concluída"
        else:
            nome_exib = cfg["nome"][:24]
            umid_str = "-"
            leits = f"0/{DEFAULT_TARGET_READINGS}"
            dmrt_str = "-"
            mrt_sens = "-"
            mrt_ref = "-"
            status = "⏳ Pendente"

        print(f"| {loc_num:02d}  | {cfg['codigo']:<10} | {nome_exib:<24} | {umid_str:<6} | {leits:<8} | {dmrt_str:<18} | {mrt_sens:<11} | {mrt_ref:<10} | {status:<11} |")

    print("+" + "-" * 5 + "+" + "-" * 12 + "+" + "-" * 26 + "+" + "-" * 8 + "+" + "-" * 10 + "+" + "-" * 20 + "+" + "-" * 13 + "+" + "-" * 12 + "+" + "-" * 13 + "+")
    pct_concluido = (concluidas_count / 6) * 100.0
    print(f"Progresso: {concluidas_count} de 6 localizações concluídas ({pct_concluido:.1f}%)")

    if len(dmrt_means) >= 2:
        g_mean, g_std, g_min, g_max = calculate_stats(dmrt_means)
        s_mean, s_std, s_min, s_max = calculate_stats(sens_means)
        print("-" * 120)
        print(f"📊 RESILIÊNCIA ENTRE LOCALIDADES ({len(dmrt_means)} locais):")
        print(f"   • DMRT Global Inter-Localidades : {g_mean:+.2f} dB (± {g_std:.2f} dB) | Amplitude Máx-Mín: {(g_max - g_min):.2f} dB")
        print(f"   • MRT Sensor Inter-Localidades  : {s_mean:.2f} dBm (± {s_std:.2f} dB) | Amplitude Máx-Mín: {(s_max - s_min):.2f} dB")
    print("=" * 120 + "\n")


# ===================================================================================
# Consolidação de Dados e Gráficos Analíticos de Resiliência
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


def update_consolidated_csv(csv_path: str, record_dict: dict, key_field: str = "local_num"):
    """Atualiza ou insere registro na tabela CSV consolidada mantendo ordenação por local."""
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
        for k in sorted(rows_by_key.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
            writer.writerow(rows_by_key[k])

    print(f"📁 Tabela consolidada atualizada: {os.path.abspath(csv_path)}")


def load_dmrt_series_for_location(csv_file: str) -> List[float]:
    """Lê a série de 300 amostras de DMRT do arquivo CSV individual de uma localidade."""
    if not csv_file or not os.path.exists(csv_file):
        return []
    vals = []
    try:
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                v = row.get("dmrt")
                if v not in (None, "", "N/A"):
                    vals.append(float(v))
    except Exception:
        pass
    return vals


def generate_consolidated_charts():
    """
    Gera os gráficos analíticos do Experimento 8 comprovando a resiliência do DMRT
    ao longo das 6 diferentes localizações sob a mesma umidade do solo.
    """
    if not os.path.exists(CONSOLIDATED_CSV):
        print(f"⚠️ Arquivo consolidado não encontrado em {CONSOLIDATED_CSV}.")
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

        if not records:
            return

        # Ordena por local_num
        records.sort(key=lambda x: int(x["local_num"]) if str(x.get("local_num", "")).isdigit() else 99)

        labels = []
        dmrt_means = []
        dmrt_stds = []
        sens_means = []
        sens_stds = []
        ref_means = []
        ref_stds = []
        sens_rssis = []
        ref_rssis = []
        dmrt_distributions = []

        for r in records:
            loc_num = int(r["local_num"]) if str(r.get("local_num", "")).isdigit() else 0
            loc_name = r.get("local_nome", f"Local {loc_num:02d}")
            short_lbl = f"L{loc_num:02d}\n({loc_name})" if len(loc_name) <= 16 else f"Local {loc_num:02d}"
            labels.append(short_lbl)

            d_m = float(r["dmrt_medio"]) if r.get("dmrt_medio") not in ("N/A", "", None) else 0.0
            d_s = float(r["dmrt_std"]) if r.get("dmrt_std") not in ("N/A", "", None) else 0.0
            s_m = float(r["sensing_mrt_filt_medio"]) if r.get("sensing_mrt_filt_medio") not in ("N/A", "", None) else 0.0
            s_s = float(r["sensing_mrt_filt_std"]) if r.get("sensing_mrt_filt_std") not in ("N/A", "", None) else 0.0
            rf_m = float(r["ref_mrt_filt_medio"]) if r.get("ref_mrt_filt_medio") not in ("N/A", "", None) else 0.0
            rf_s = float(r["ref_mrt_filt_std"]) if r.get("ref_mrt_filt_std") not in ("N/A", "", None) else 0.0
            s_r = float(r["sensing_rssi_medio"]) if r.get("sensing_rssi_medio") not in ("N/A", "", None) else 0.0
            rf_r = float(r["ref_rssi_medio"]) if r.get("ref_rssi_medio") not in ("N/A", "", None) else 0.0

            dmrt_means.append(d_m)
            dmrt_stds.append(d_s)
            sens_means.append(s_m)
            sens_stds.append(s_s)
            ref_means.append(rf_m)
            ref_stds.append(rf_s)
            sens_rssis.append(s_r)
            ref_rssis.append(rf_r)

            # Tenta carregar a distribuição de 300 leituras do CSV individual
            csv_ind = r.get("arquivo_csv", "")
            if not csv_ind or not os.path.exists(csv_ind):
                code = r.get("local_codigo", f"local_{loc_num:02d}")
                csv_ind = os.path.join(EXP8_DIR, f"{code}_resultados.csv")
            dist = load_dmrt_series_for_location(csv_ind)
            dmrt_distributions.append(dist if dist else [d_m])

        x_idx = list(range(len(records)))
        u_val = float(records[0].get("umidade_pct", 48.0))
        valid_dmrts = [d for d in dmrt_means if d != 0.0]
        g_dmrt_mean, g_dmrt_std, g_dmrt_min, g_dmrt_max = calculate_stats(valid_dmrts)
        g_sens_mean, g_sens_std, g_sens_min, g_sens_max = calculate_stats([s for s in sens_means if s > 0])

        # ---------------------------------------------------------------------------
        # Gráfico 1: Variação do DMRT nas Diferentes Localidades (Painel Duplo)
        # ---------------------------------------------------------------------------
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6), dpi=150)

        # Painel Esquerdo: Estabilidade / Variação do DMRT nas 6 Localidades
        ax1.errorbar(
            x_idx, dmrt_means, yerr=dmrt_stds, fmt="-o",
            color="#2ca02c", ecolor="#66c2a5", elinewidth=2, capsize=5,
            linewidth=2.5, markersize=8, label="DMRT Médio por Localidade (±1σ)"
        )
        if valid_dmrts:
            ax1.axhline(
                g_dmrt_mean, color="#006d2c", linestyle="--", linewidth=1.8,
                label=f"Média Global DMRT: {g_dmrt_mean:+.2f} dB (σ={g_dmrt_std:.2f} dB)"
            )
            ax1.fill_between(
                x_idx,
                [g_dmrt_mean - g_dmrt_std] * len(x_idx),
                [g_dmrt_mean + g_dmrt_std] * len(x_idx),
                color="#2ca02c", alpha=0.15, label="Faixa de Estabilidade (±1σ Global)"
            )

        for i, val in enumerate(dmrt_means):
            ax1.annotate(
                f"{val:+.2f} dB",
                (x_idx[i], dmrt_means[i]),
                textcoords="offset points", xytext=(0, 12),
                ha="center", fontsize=9, fontweight="bold", color="#00441b"
            )

        ax1.set_title("Resiliência do DMRT nas Diferentes Localidades", fontsize=11, fontweight="bold")
        ax1.set_xlabel("Localizações Avaliadas", fontsize=10)
        ax1.set_ylabel("DMRT = MRT_sens - MRT_ref (dB)", fontsize=10)
        ax1.set_xticks(x_idx)
        ax1.set_xticklabels(labels, fontsize=9)
        if valid_dmrts:
            y_margin = max(2.5, (g_dmrt_max - g_dmrt_min) * 1.2 + 1.5)
            ax1.set_ylim(g_dmrt_mean - y_margin, g_dmrt_mean + y_margin)
        ax1.grid(True, linestyle="--", alpha=0.5)
        ax1.legend(loc="best", fontsize=9, frameon=True)

        # Painel Direito: MRT Sensor e MRT Referência vs DMRT (Cancelamento de Modo Comum)
        ax2.errorbar(
            x_idx, sens_means, yerr=sens_stds, fmt="-s",
            color="#1f77b4", linewidth=2, markersize=7, capsize=4,
            label=f"MRT Sensoriamento (σ={g_sens_std:.2f} dB)"
        )
        ax2.errorbar(
            x_idx, ref_means, yerr=ref_stds, fmt="-^",
            color="#ff7f0e", linewidth=2, markersize=7, capsize=4,
            label="MRT Referência (Canal/Ambiente)"
        )
        ax2.plot(
            x_idx, dmrt_means, "-o",
            color="#2ca02c", linewidth=2.2, markersize=7,
            label="DMRT Diferencial (Sens - Ref)"
        )

        ax2.set_title("Cancelamento de Modo Comum: MRT Bruto vs DMRT", fontsize=11, fontweight="bold")
        ax2.set_xlabel("Localizações Avaliadas", fontsize=10)
        ax2.set_ylabel("Limiar de Potência / Diferencial (dBm / dB)", fontsize=10)
        ax2.set_xticks(x_idx)
        ax2.set_xticklabels(labels, fontsize=9)
        ax2.grid(True, linestyle="--", alpha=0.5)
        ax2.legend(loc="best", fontsize=9, frameon=True)

        fig.suptitle(
            f"Experimento 8: Variação do DMRT em {len(records)} Diferentes Localizações sob Mesma Umidade ({u_val:.1f}%)\n"
            f"Comprovação da Resiliência Ambiental da Métrica Diferencial (300 medições/local)",
            fontsize=12, fontweight="bold"
        )
        fig.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(CHART_DMRT_LOCATIONS)), exist_ok=True)
        plt.savefig(CHART_DMRT_LOCATIONS, format="png", bbox_inches="tight")
        plt.close()
        print(f"📈 Gráfico de Variação do DMRT por Localidade gerado: {os.path.abspath(CHART_DMRT_LOCATIONS)}")

        # ---------------------------------------------------------------------------
        # Gráfico 2: Distribuição Boxplot (300 leituras/local) e Comparativo de Barras
        # ---------------------------------------------------------------------------
        fig, (bx1, bx2) = plt.subplots(1, 2, figsize=(15, 6), dpi=150)

        # Subgráfico 1: Boxplot das 300 medições de DMRT em cada localidade
        bp = bx1.boxplot(
            dmrt_distributions,
            positions=x_idx,
            widths=0.45,
            patch_artist=True,
            showmeans=True,
            meanprops={"marker": "D", "markerfacecolor": "#00441b", "markeredgecolor": "white", "markersize": 6}
        )
        for patch in bp["boxes"]:
            patch.set_facecolor("#a1d99b")
            patch.set_edgecolor("#2ca02c")
            patch.set_alpha(0.85)
        for median in bp["medians"]:
            median.set_color("#00441b")
            median.set_linewidth(2)

        if valid_dmrts:
            bx1.axhline(
                g_dmrt_mean, color="#006d2c", linestyle="--", linewidth=1.5,
                label=f"Média Global ({g_dmrt_mean:+.2f} dB)"
            )
            bx1.legend(loc="best", fontsize=9)

        bx1.set_title("Distribuição das 300 Medições de DMRT por Localidade", fontsize=11, fontweight="bold")
        bx1.set_xlabel("Localizações Avaliadas", fontsize=10)
        bx1.set_ylabel("DMRT (dB)", fontsize=10)
        bx1.set_xticks(x_idx)
        bx1.set_xticklabels(labels, fontsize=9)
        bx1.grid(True, linestyle="--", alpha=0.5, axis="y")

        # Subgráfico 2: Barras Agrupadas (DMRT vs MRT Sensor vs MRT Ref)
        width = 0.26
        bx2.bar([i - width for i in x_idx], dmrt_means, width, yerr=dmrt_stds, capsize=3, label="DMRT Médio (dB)", color="#2ca02c")
        bx2.bar(x_idx, sens_means, width, yerr=sens_stds, capsize=3, label="MRT Sensor Médio (dBm)", color="#1f77b4")
        bx2.bar([i + width for i in x_idx], ref_means, width, yerr=ref_stds, capsize=3, label="MRT Ref Médio (dBm)", color="#ff7f0e")

        bx2.set_title("Comparativo de Magnitude por Localidade (DMRT vs MRTs)", fontsize=11, fontweight="bold")
        bx2.set_xlabel("Localizações Avaliadas", fontsize=10)
        bx2.set_ylabel("Magnitude (dB / dBm)", fontsize=10)
        bx2.set_xticks(x_idx)
        bx2.set_xticklabels(labels, fontsize=9)
        bx2.grid(True, linestyle="--", alpha=0.4, axis="y")
        bx2.legend(loc="best", fontsize=9)

        fig.suptitle(
            f"Experimento 8: Dispersão Amostral (300 leituras/local) e Comparativo de Métricas ({u_val:.1f}% Umidade)",
            fontsize=12, fontweight="bold"
        )
        fig.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(CHART_METRICS_COMPARISON)), exist_ok=True)
        plt.savefig(CHART_METRICS_COMPARISON, format="png", bbox_inches="tight")
        plt.close()
        print(f"📈 Gráfico Comparativo de Métricas e Boxplot gerado: {os.path.abspath(CHART_METRICS_COMPARISON)}")

    except Exception as e:
        print(f"⚠️ Não foi possível gerar gráficos consolidados: {e}")


# ===================================================================================
# Pipeline Principal de Execução
# ===================================================================================

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Experimento 8: Resiliência do DMRT em 6 Diferentes Localizações sob Mesma Umidade"
    )
    parser.add_argument(
        "--local", "--bateria", dest="local", type=int, choices=list(range(1, 7)), default=None,
        help="Número da localização (1 a 6) onde o setup foi posicionado."
    )
    parser.add_argument(
        "--nome", "--posicao", dest="nome_local", type=str, default=None,
        help="Nome ou descrição opcional da localização (ex: 'Bancada Central', 'Sala 2', 'Corredor')."
    )
    parser.add_argument(
        "--umidade", type=float, default=None,
        help="Umidade fixa do solo medida pelo sensor RainPoint (ex: 48.0%%). Se omitida, usa o último valor gravado."
    )
    parser.add_argument(
        "--readings", type=int, default=DEFAULT_TARGET_READINGS,
        help=f"Quantidade de medições de DMRT por localidade (padrão: {DEFAULT_TARGET_READINGS})"
    )
    parser.add_argument(
        "--dwell", type=float, default=0.12,
        help="Tempo de permanência RF em segundos por nível (padrão: 0.12s)"
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
        help="Exibe a tabela consolidada das 6 localizações e encerra"
    )
    parser.add_argument(
        "--plot", "--gerar-graficos", dest="plot_only", action="store_true",
        help="Regenera os gráficos consolidados de variação do DMRT a partir dos dados já coletados e encerra"
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    # Se o usuário solicitou apenas visualização de status
    if args.status:
        show_experiment_status()
        return

    # Se o usuário solicitou apenas regenerar os gráficos consolidados
    if args.plot_only:
        generate_consolidated_charts()
        show_experiment_status()
        return

    # 1. Determina a Localização Atual (1 a 6)
    local_num = args.local if args.local is not None else 1
    cfg = LOCALIDADES_CONFIG[local_num]
    local_code = cfg["codigo"]
    local_name = args.nome_local.strip() if args.nome_local else cfg["nome"]

    # Determina umidade fixa do solo
    if args.umidade is not None:
        umidade_pct = args.umidade
    else:
        last_u = get_last_recorded_moisture()
        umidade_pct = last_u if last_u is not None else 48.0

    csv_path = os.path.join(EXP8_DIR, f"{local_code}_resultados.csv")
    chart_path = os.path.join(EXP8_DIR, f"{local_code}_grafico.png")
    setup_title = f"Experimento 8 - {local_code.upper()} ({local_name} | Umidade: {umidade_pct:.1f}%)"

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
        reader = MockReaderForExp8(
            port=args.port,
            baudrate=args.baudrate,
            sensing_epc=sensing_epc,
            ref_epc=ref_epc,
            moisture_pct=umidade_pct,
            local_num=local_num
        )
        reader.connect()

    target_readings = args.readings

    # 4. Banner Informativo do Setup
    print("=" * 112)
    print("      IN-R200 UHF RFID Reader - EXPERIMENTO 8: RESILIÊNCIA DO DMRT EM 6 LOCALIZAÇÕES")
    print("=" * 112)
    print(f"📍 Localização         : {local_num:02d} de 06 — {local_name} ({local_code})")
    print(f"💧 Umidade do Solo Fixa: {umidade_pct:.1f}% (Sensor RainPoint)")
    print(f"🏷️  Tag Sensoriamento   : {sensing_epc} (Vaso de solo)")
    print(f"🏷️  Tag Referência      : {ref_epc} (Isolada de referência)")
    print(f"⚡ Faixa de Potência   : {args.min_power:.1f} dBm a {args.max_power:.1f} dBm (passo {args.power_step} dBm com early-stop)")
    print(f"⏱️  Tempo Dwell/Nível  : {args.dwell:.3f} s")
    print(f"🎯 Meta de Leituras    : {target_readings} medições de DMRT")
    print(f"📁 Arquivo CSV         : {csv_path}")
    print(f"📈 Gráfico PNG         : {chart_path}")
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

    print(f"\n📡 Iniciando as {target_readings} medições na {local_name} ({local_code})...")
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
                rotation_deg=0.0,
                position=local_code
            )

            # Log resumido por linha
            s_str = f"S:{s_data['filtered_mrt']:.1f}dBm" if s_data else "S:MISS"
            r_str = f"R:{r_data['filtered_mrt']:.1f}dBm" if r_data else "R:MISS"
            d_str = f"DMRT:{dmrt_val:+.2f}dB" if dmrt_val is not None else "DMRT:N/A"
            print(f"  ⚡ [{reading_counter:04d}/{target_readings}] {local_code} | {s_str} | {r_str} | {d_str} | Tempo: {dt_sweep:.2f}s")

            # Tabela periódica
            if reading_counter % 10 == 0 or reading_counter == target_readings:
                print_table(
                    reading_counter, target_readings, local_num, local_code, local_name,
                    umidade_pct, sensing_epc, ref_epc,
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

        dmrt_mean, dmrt_std, dmrt_min, dmrt_max = calculate_stats(dmrt_hist)

        # Registro para tabela consolidada
        record_entry = {
            "local_num": local_num,
            "local_codigo": local_code,
            "local_nome": local_name,
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
            "dmrt_min": f"{dmrt_min:.2f}" if dmrt_hist else "N/A",
            "dmrt_max": f"{dmrt_max:.2f}" if dmrt_hist else "N/A",
            "sensing_rssi_medio": f"{s_rssi_mean:.1f}",
            "sensing_rssi_std": f"{s_rssi_std:.2f}",
            "ref_rssi_medio": f"{r_rssi_mean:.1f}",
            "ref_rssi_std": f"{r_rssi_std:.2f}",
            "sensing_epc": sensing_epc,
            "reference_epc": ref_epc,
            "arquivo_csv": csv_path,
            "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        update_consolidated_csv(CONSOLIDATED_CSV, record_entry, key_field="local_num")
        generate_consolidated_charts()

    # Relatório Final
    s_rssi_fmt = f"{s_rssi_mean:.1f} dBm" if s_rssi_mean < 0 else f"-{s_rssi_mean:.1f} dBm"
    r_rssi_fmt = f"{r_rssi_mean:.1f} dBm" if r_rssi_mean < 0 else f"-{r_rssi_mean:.1f} dBm"

    print("\n" + "=" * 112)
    print(f"        RELATÓRIO FINAL: {setup_title.upper()}")
    print("=" * 112)
    print(f"📌 Tag Sensoriamento : {sensing_epc} (Vaso de solo)")
    print(f"📌 Tag Referência    : {ref_epc} (Isolada de referência)")
    print(f"📍 Localização       : {local_num:02d}/06 - {local_name} ({local_code})")
    print(f"💧 Umidade Fixa Solo : {umidade_pct:.1f}%")
    print(f"🔢 Medições          : {reading_counter} realizadas ({len(dmrt_hist)} pares válidos com DMRT)")
    print("-" * 112)
    print(f"🎯 Sensor MRT (EMA)  : {s_filt_mean:.2f} dBm  (± {s_filt_std:.2f} dB) | RSSI: {s_rssi_fmt}")
    print(f"🎯 Referência MRT    : {r_filt_mean:.2f} dBm  (± {r_filt_std:.2f} dB) | RSSI: {r_rssi_fmt}")
    print(f"⚖️  DMRT Médio (ΔMRT): {dmrt_mean:+.2f} dB   (± {dmrt_std:.2f} dB)")
    print("-" * 112)
    print(f"👉 RESULTADO DA LOCALIDADE {local_num:02d}: DMRT = {dmrt_mean:+.2f} dB | Sensor MRT = {s_filt_mean:.2f} dBm")
    print("=" * 112)
    print(f"✅ CSV da localidade salvo em       : {os.path.abspath(csv_path)}")
    print(f"✅ Gráfico da localidade salvo em   : {os.path.abspath(chart_path)}")
    print(f"✅ Tabela consolidada salva em      : {os.path.abspath(CONSOLIDATED_CSV)}")
    if os.path.exists(CHART_DMRT_LOCATIONS):
        print(f"✅ Gráfico Variação DMRT gerado em  : {os.path.abspath(CHART_DMRT_LOCATIONS)}")
    if os.path.exists(CHART_METRICS_COMPARISON):
        print(f"✅ Gráfico Comparativo gerado em    : {os.path.abspath(CHART_METRICS_COMPARISON)}")
    print("=" * 112)


if __name__ == "__main__":
    main()
