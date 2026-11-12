"""
===================================================================================
 Experimento 10: Medição de DMRT (200 Leituras) + RSSI Fixo a 26 dBi (+200 Leituras)
 Tags Mapeadas: Pares 09-01 a 09-18 (anotacoes.md / tags_mapeadas.json)
===================================================================================
 Descrição:
  - Semelhante ao Experimento 9, utilizando os 18 pares de tags mapeados em
    anotacoes.md (nomeados de 09-01 a 09-18).
  - Não impõe ordem de execução: qualquer teste/par pode ser executado em qualquer
    ordem, repetido ou renomeado livremente.
  - Permite alterar os valores (EPCs) das tags a qualquer momento:
      * Editando diretamente o dicionário TAG_PAIRS_EXP10 neste arquivo (main.py)
      * Editando o arquivo anotacoes.md
      * Passando --tag <EPC_SENS> e/ou --ref <EPC_REF> na linha de comando
      * Ou salvando uma alteração permanente via --set-tag <PAR> <EPC_SENS> <EPC_REF>
  - Em cada execução, realiza duas etapas sequenciais nas tags selecionadas:
      1) Etapa 1 (DMRT): 200 leituras padrões de DMRT (varredura de potência RF
         de 15.0 a 26.0 dBm com early-stop).
      2) Etapa 2 (RSSI @ 26 dBi): Fixa a potência do leitor em 26.0 dBi (26 dBm)
         e realiza +200 leituras apenas do valor de RSSI daquelas tags.
  - Salva os dados individuais e atualiza a tabela consolidada
    (experimento_10/consolidado_exp10.csv), sem gerar gráfico de curva consolidado
    automaticamente (o gráfico de curva será compilado manualmente pelo usuário).
===================================================================================
 Exemplos de uso (qualquer ordem de execução):
   # 1. Executar diretamente pelo código do par (09-01 a 09-18 ou 1 a 18)
   python main.py 09-01
   python main.py 09-15
   python main.py 4

   # 2. Executar dando um nome livre e indicando o par de tags (--par / -p)
   python main.py xp-100-4 --par 09-04
   python main.py --nome amostra_turfa --par 09-12

   # 3. Executar passando um nome terminado no número do par (identifica 09-XX automaticamente)
   python main.py xp-fin-100-4
   python main.py xp-fin-500-18

   # 4. Alterar/sobrescrever manualmente os EPCs das tags na execução
   python main.py 09-06 --tag E2806995000040136FD0E175 --ref E2806995000040136FD0ED75

   # 5. Atualizar permanentemente o EPC de um par (09-01 a 09-18) em anotacoes.md e JSON
   python main.py --set-tag 09-06 E2806995000040136FD0E175 E2806995000040136FD0ED75

   # 6. Listar todos os 18 pares de tags (09-01 a 09-18) ou ver o status consolidado
   python main.py --tags
   python main.py --status
===================================================================================
"""

import os
import re
import sys
import time
import csv
import json
import math
import random
import unicodedata
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from in_r200_driver import INR200Reader
from mrt_calculator import MRTCalculator
from dmrt_exporter import DMRTExporter

# Diretórios e caminhos padrão do Experimento 10
EXP10_DIR = "experimento_10"
DEFAULT_MD_FILE = os.path.join(EXP10_DIR, "experimento10.md")
ANOTACOES_FILE = "anotacoes.md"
DEFAULT_JSON_FILE = "tags_mapeadas.json"
CONSOLIDATED_CSV = os.path.join(EXP10_DIR, "consolidado_exp10.csv")

# Padrão: 200 leituras de DMRT + 200 leituras de RSSI com potência fixa em 26 dBi (26.0 dBm)
DEFAULT_TARGET_READINGS = 200
DEFAULT_RSSI_READINGS = 200
DEFAULT_FIXED_RSSI_POWER = 26.0
TAG_TIMEOUT = 10.0

# ===================================================================================
# Catálogo Editável de Pares de Tags (09-01 a 09-18) conforme anotacoes.md
# Você pode alterar qualquer EPC diretamente aqui, em anotacoes.md, ou via --tag/--ref
# Formato: "09-XX": ("EPC_SENSORIAMENTO", "EPC_REFERENCIA")
# ===================================================================================
TAG_PAIRS_EXP10: Dict[str, Tuple[str, str]] = {
    "09-01": ("E2806995000040136FD0C575", "E2806995000040136FD0C975"),
    "09-02": ("E2806995000040136FD0D175", "E2806995000050136FD0CD75"),
    "09-03": ("E2806995000050136FD0D975", "E2806995000050136FD0D575"),
    "09-04": ("E2806995000040136FD0DD75", "E2806995000040136FD0E175"),
    "09-05": ("E2806995000050136FD0E575", "E2806995000050136FD0E975"),
    "09-06": ("E2806995000050136FD0F175", "E2806995000040136FD0ED75"),
    "09-07": ("E2806995000040136FD0F975", "E2806995000040136FD0F575"),
    "09-08": ("E2806995000050136FD0FD75", "E2806995000040136FD10175"),
    "09-09": ("E2806995000050136FD10575", "E2806995000050136FD10975"),
    "09-10": ("E2806995000040136FD0D175", "E2806995000050136FD11175"),
    "09-11": ("E2806995000040136FD11575", "E2806995000040136FD11975"),
    "09-12": ("E2806995000050136FD11D75", "E2806995000050136FD12175"),
    "09-13": ("E2806995000040136FD12575", "E2806995000040136FD12975"),
    "09-14": ("E2806995000050136FD12D75", "E2806995000040136FD13175"),
    "09-15": ("E2806995000050136FD13575", "E2806995000050136FD13975"),
    "09-16": ("E2806995000040136FD13D75", "E2806995000050136FD14175"),
    "09-17": ("E2806995000040136FD14575", "E2806995000040136FD14975"),
    "09-18": ("E2806995000050136FD14D75", "E2806995000040136FD0BD75"),
}

# Snapshot original para detectar se o usuário editou anotacoes.md ou TAG_PAIRS_EXP10
_INITIAL_ANOTACOES_SNAPSHOT: Dict[str, Tuple[str, str]] = dict(TAG_PAIRS_EXP10)

# Tags padrão caso nenhum par específico seja informado
DEFAULT_SENSING_EPC = TAG_PAIRS_EXP10["09-01"][0]
DEFAULT_REF_EPC     = TAG_PAIRS_EXP10["09-01"][1]

# Curva empírica de referência (Experimento 6) usada apenas para o modo --simulado
EXP6_CURVE = [
    (22.0, 15.00), (30.0, 15.11), (45.0, 15.62), (55.0, 17.47),
    (65.0, 20.40), (78.0, 24.68), (93.0, 25.56)
]

# Colunas oficiais do CSV consolidado do Experimento 10
CONSOLIDATED_FIELDS = [
    "medicao",
    "medicao_codigo",
    "nome_medicao",
    "par_tags",
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
    "leituras_planejadas_rssi_26dbm",
    "leituras_executadas_rssi_26dbm",
    "leituras_detectadas_sens_rssi_26dbm",
    "leituras_detectadas_ref_rssi_26dbm",
    "taxa_deteccao_sens_rssi_26dbm_pct",
    "sensing_rssi_26dbm_medio",
    "sensing_rssi_26dbm_std",
    "sensing_rssi_26dbm_min",
    "sensing_rssi_26dbm_max",
    "ref_rssi_26dbm_medio",
    "ref_rssi_26dbm_std",
    "ref_rssi_26dbm_min",
    "ref_rssi_26dbm_max",
    "drssi_26dbm_medio",
    "drssi_26dbm_std",
    "sensing_epc",
    "reference_epc",
    "arquivo_csv",
    "arquivo_rssi_csv",
    "arquivo_grafico",
    "data_hora",
]

# Armazenamento em memória das tags escaneadas
scanned_tags: Dict[str, dict] = {}


# ===================================================================================
# Utilitários de Nomeação e Formatação
# ===================================================================================

def normalize_pair_id(raw_id: Optional[str]) -> Optional[str]:
    """
    Normaliza identificadores como '1', '01', '9-01', '09-01', '9_1', '09_18'
    para a chave canônica '09-01' .. '09-18'. Retorna None se não corresponder a 1..18.
    """
    if not raw_id:
        return None
    text = raw_id.strip()
    m_full = re.match(r"^0?9[-_]?(\d{1,2})$", text)
    if m_full:
        idx = int(m_full.group(1))
        if 1 <= idx <= 18:
            return f"09-{idx:02d}"
    if text.isdigit():
        idx = int(text)
        if 1 <= idx <= 18:
            return f"09-{idx:02d}"
    return None


def infer_pair_from_name(name: Optional[str]) -> Optional[str]:
    """
    Tenta identificar automaticamente o par '09-01'..'09-18' a partir do nome da medição.
    Aceita nomes como:
      - '09-01', '9-01', '1', '01'
      - 'xp-fin-100-4' (extrai o sufixo 4 -> '09-04')
      - 'amostra_09-12' ou 'vaso_15'
    """
    if not name:
        return None
    direct = normalize_pair_id(name)
    if direct:
        return direct

    text = name.strip()
    m_explicit = re.search(r"(?:^|[^0-9])0?9[-_](\d{1,2})(?:$|[^0-9])", text)
    if m_explicit:
        idx = int(m_explicit.group(1))
        if 1 <= idx <= 18:
            return f"09-{idx:02d}"

    m_suffix = re.search(r"[-_](\d{1,2})$", text)
    if m_suffix:
        idx = int(m_suffix.group(1))
        if 1 <= idx <= 18:
            return f"09-{idx:02d}"

    return None


def slugify_name(name: str) -> str:
    """
    Converte qualquer nome livre de medição em um identificador seguro para arquivos.
    Ex: '09-01' -> '09_01'
        'xp-fin-100-4' -> 'xp_fin_100_4'
    """
    raw = name.strip()
    pair_id = normalize_pair_id(raw)
    if pair_id:
        return pair_id.replace("-", "_")

    normalized = unicodedata.normalize("NFKD", raw)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text.lower()).strip("_")
    return slug or f"medicao_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def format_display_name(name: str) -> str:
    """Retorna um rótulo legível para exibição no terminal."""
    raw = name.strip()
    pair_id = normalize_pair_id(raw)
    if pair_id:
        return pair_id
    return raw


# ===================================================================================
# Simulação Virtual (Mock) para Testes Offline do Experimento 10
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


class MockReaderForExp10:
    """Simulador físico para testes offline do Experimento 10 (DMRT + RSSI @ 26 dBi)."""
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200,
                 sensing_epc: str = DEFAULT_SENSING_EPC, ref_epc: str = DEFAULT_REF_EPC,
                 moisture_pct: Optional[float] = None, medicao_label: str = "09-01"):
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
        print(f"⚡ [MODO SIMULADO EXP10] Conectado virtualmente em {self.port} ({self.medicao_label})")
        return True

    def get_module_info(self) -> str:
        return "IN-R200 M100 V1.0 (SIMULADO EXP10)"

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
# Resolução e Gerenciamento dos Pares de Tags (09-01 a 09-18)
# ===================================================================================

def is_valid_hex_epc(epc: Optional[str]) -> bool:
    """Verifica se a string é um código EPC hexadecimal válido (24 caracteres)."""
    if not epc:
        return False
    clean = epc.strip()
    return len(clean) == 24 and all(c in "0123456789ABCDEFabcdef" for c in clean)


def load_pairs_from_anotacoes(anotacoes_path: str = ANOTACOES_FILE) -> Dict[str, Tuple[str, str]]:
    """
    Lê os pares 09-01 a 09-18 (ou 9-01 a 9-18) diretamente de anotacoes.md.
    Formato esperado em anotacoes.md:
      9-01: E2806995000040136FD0C575 - E2806995000040136FD0C975
    """
    pairs: Dict[str, Tuple[str, str]] = {}
    if not os.path.exists(anotacoes_path):
        return pairs
    try:
        with open(anotacoes_path, "r", encoding="utf-8") as f:
            content = f.read()
        pattern = re.compile(
            r"^\s*(0?9-\d{2})\s*:\s*([0-9A-Fa-f]{24})\s*-\s*([0-9A-Fa-f]{24})\s*$",
            re.MULTILINE
        )
        for match in pattern.finditer(content):
            norm_key = normalize_pair_id(match.group(1))
            sens = match.group(2).strip().upper()
            ref = match.group(3).strip().upper()
            if norm_key and is_valid_hex_epc(sens) and is_valid_hex_epc(ref):
                pairs[norm_key] = (sens, ref)
    except Exception as e:
        print(f"⚠️ Aviso ao ler {anotacoes_path}: {e}")
    return pairs


def load_pairs_from_json(json_path: str = DEFAULT_JSON_FILE) -> Dict[str, Tuple[str, str]]:
    """Carrega os pares 09-01 a 09-18 a partir de tags_mapeadas.json."""
    pairs: Dict[str, Tuple[str, str]] = {}
    if not os.path.exists(json_path):
        return pairs
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("pares", []):
            norm_key = normalize_pair_id(str(item.get("experimento", "")))
            sens = str(item.get("sensoriamento", "")).strip().upper()
            ref = str(item.get("referencia", "")).strip().upper()
            if norm_key and is_valid_hex_epc(sens) and is_valid_hex_epc(ref):
                pairs[norm_key] = (sens, ref)
    except Exception as e:
        print(f"⚠️ Aviso ao ler {json_path}: {e}")
    return pairs


def get_effective_tag_pairs() -> Dict[str, Tuple[str, str]]:
    """
    Combina de forma inteligente o catálogo TAG_PAIRS_EXP10 (em main.py),
    anotacoes.md e tags_mapeadas.json:
      - Se o usuário alterou anotacoes.md em relação ao snapshot original, usa o valor de anotacoes.md.
      - Se o usuário alterou TAG_PAIRS_EXP10 diretamente em main.py, respeita a alteração em main.py.
    """
    effective = dict(TAG_PAIRS_EXP10)
    json_pairs = load_pairs_from_json(DEFAULT_JSON_FILE)
    md_pairs = load_pairs_from_anotacoes(ANOTACOES_FILE)

    for key in sorted(effective.keys()):
        code_val = TAG_PAIRS_EXP10.get(key)
        base_val = _INITIAL_ANOTACOES_SNAPSHOT.get(key)
        md_val = md_pairs.get(key)
        json_val = json_pairs.get(key)

        # Se o usuário editou diretamente TAG_PAIRS_EXP10 no código, prioriza o código
        if code_val != base_val:
            effective[key] = (code_val[0].upper(), code_val[1].upper())
        # Se o usuário editou anotacoes.md, usa anotacoes.md
        elif md_val and md_val != base_val:
            effective[key] = (md_val[0].upper(), md_val[1].upper())
        # Se o usuário editou tags_mapeadas.json, usa tags_mapeadas.json
        elif json_val and json_val != base_val:
            effective[key] = (json_val[0].upper(), json_val[1].upper())
        elif md_val:
            effective[key] = (md_val[0].upper(), md_val[1].upper())

    return effective


def update_pair_in_files(pair_id: str, sens_epc: str, ref_epc: str) -> bool:
    """
    Atualiza permanentemente os EPCs de um par (09-01 a 09-18) em anotacoes.md e tags_mapeadas.json.
    """
    norm_key = normalize_pair_id(pair_id)
    if not norm_key:
        print(f"❌ Identificador de par inválido: '{pair_id}'. Use 09-01 a 09-18 (ou 1 a 18).")
        return False
    sens_clean = sens_epc.strip().upper()
    ref_clean = ref_epc.strip().upper()
    if not (is_valid_hex_epc(sens_clean) and is_valid_hex_epc(ref_clean)):
        print("❌ EPC inválido! Cada EPC deve conter exatamente 24 caracteres hexadecimais.")
        return False

    idx = int(norm_key.split("-")[1])
    short_key = f"9-{idx:02d}"

    # 1. Atualiza em anotacoes.md
    if os.path.exists(ANOTACOES_FILE):
        with open(ANOTACOES_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        pattern = re.compile(
            rf"^(\s*0?9-{idx:02d}\s*:\s*)([0-9A-Fa-f]{{24}})(\s*-\s*)([0-9A-Fa-f]{{24}})(\s*)$",
            re.MULTILINE
        )
        if pattern.search(content):
            new_content = pattern.sub(rf"\g<1>{sens_clean}\g<3>{ref_clean}\g<5>", content)
            with open(ANOTACOES_FILE, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"✅ Par {norm_key} atualizado em {ANOTACOES_FILE}: {sens_clean} - {ref_clean}")

    # 2. Atualiza em tags_mapeadas.json
    if os.path.exists(DEFAULT_JSON_FILE):
        try:
            with open(DEFAULT_JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("pares", []):
                if normalize_pair_id(str(item.get("experimento", ""))) == norm_key:
                    item["sensoriamento"] = sens_clean
                    item["referencia"] = ref_clean
            with open(DEFAULT_JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"✅ Par {norm_key} ({short_key}) atualizado em {DEFAULT_JSON_FILE}")
        except Exception as e:
            print(f"⚠️ Aviso ao atualizar {DEFAULT_JSON_FILE}: {e}")

    TAG_PAIRS_EXP10[norm_key] = (sens_clean, ref_clean)
    return True


def show_configured_tags():
    """Exibe a tabela completa dos 18 pares de tags (09-01 a 09-18) ativos."""
    pairs = get_effective_tag_pairs()
    print("\n" + "=" * 92)
    print("        CATÁLOGO DE PARES DE TAGS DO EXPERIMENTO 10 (09-01 a 09-18) - anotacoes.md")
    print("=" * 92)
    print(f"| {'Par':<7} | {'Tag de Sensoriamento (EPC)':<28} | {'Tag de Referência (EPC)':<28} | {'Status':<16} |")
    sep = "+" + "-" * 9 + "+" + "-" * 30 + "+" + "-" * 30 + "+" + "-" * 18 + "+"
    print(sep)
    for key in sorted(pairs.keys()):
        sens, ref = pairs[key]
        modified = "Editado" if (sens, ref) != _INITIAL_ANOTACOES_SNAPSHOT.get(key) else "Padrão (Mapeado)"
        print(f"| {key:<7} | {sens:<28} | {ref:<28} | {modified:<16} |")
    print(sep)
    print("💡 Para alterar os valores de qualquer tag:")
    print("   - Edite em 'anotacoes.md' ou no dicionário TAG_PAIRS_EXP10 em 'main.py'")
    print("   - Ou execute: python main.py --set-tag 09-XX <EPC_SENSORIAMENTO> <EPC_REFERENCIA>")
    print("   - Ou sobrescreva em uma leitura: python main.py 09-XX --tag <EPC_SENS> --ref <EPC_REF>")
    print("=" * 92 + "\n")


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
# Leitura de RSSI em Potência Fixa (26 dBi / 26.0 dBm)
# ===================================================================================

def read_tags_rssi_at_fixed_power(
    reader,
    sensing_epc: str,
    ref_epc: str,
    dwell_time: float = 0.12
) -> Dict[str, dict]:
    """
    Realiza uma leitura rápida do RSSI das tags de sensoriamento e referência
    com a potência já fixada em 26 dBi (26.0 dBm).
    Se a tag de referência (sinal forte no ar) preencher os rounds da rajada antes da tag
    de sensoriamento (no solo), executa uma busca direcionada (target_epc) para a tag
    faltante, garantindo que nenhuma resposta válida seja perdida.
    """
    sens_key = sensing_epc.upper()
    ref_key = ref_epc.upper()
    timeout = max(0.08, dwell_time)

    detected: Dict[str, dict] = {}
    if hasattr(reader, "read_multi_tag"):
        burst = reader.read_multi_tag(loop_count=4, timeout=timeout)
        for epc, info in burst.items():
            epc_u = epc.upper()
            if epc_u in (sens_key, ref_key):
                detected[epc_u] = info

        # Busca individual caso uma das tags do par não tenha entrado na primeira rajada
        for target_key in (sens_key, ref_key):
            if target_key not in detected:
                single = reader.read_multi_tag(
                    loop_count=3,
                    timeout=timeout,
                    target_epc=target_key
                )
                if target_key in single:
                    detected[target_key] = single[target_key]
    elif hasattr(reader, "read_single_tag"):
        res = reader.read_single_tag(timeout=timeout)
        if res:
            epc, rssi, pc = res
            detected[epc.upper()] = {"rssi": rssi, "pc": pc, "count": 1}

    return detected


# ===================================================================================
# Exibição Formatada no Terminal (Etapa 1: DMRT e Etapa 2: RSSI @ 26 dBi)
# ===================================================================================

def is_tag_active(epc: str, current_time: float) -> bool:
    """Retorna True se a tag foi detectada recentemente."""
    if epc not in scanned_tags:
        return False
    return (current_time - scanned_tags[epc]["last_seen"]) <= TAG_TIMEOUT


def fmt_rssi(value: float) -> str:
    return f"{value:.1f} dBm" if value < 0 else f"-{value:.1f} dBm"


def print_table_dmrt(
    reading_counter: int,
    target_readings: int,
    med_label: str,
    pair_label: str,
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
    """Exibe tabela no terminal durante a Etapa 1 (varreduras de DMRT)."""
    pct = (reading_counter / target_readings) * 100.0

    s_mean_filt = sum(sens_hist_filt) / len(sens_hist_filt) if sens_hist_filt else 0.0
    s_mean_rssi = sum(sens_hist_rssi) / len(sens_hist_rssi) if sens_hist_rssi else 0.0
    r_mean_filt = sum(ref_hist_filt) / len(ref_hist_filt) if ref_hist_filt else 0.0
    r_mean_rssi = sum(ref_hist_rssi) / len(ref_hist_rssi) if ref_hist_rssi else 0.0
    dmrt_mean = sum(dmrt_hist) / len(dmrt_hist) if dmrt_hist else 0.0

    extras = [f"PAR: {pair_label}"]
    if rainpoint_pct is not None:
        extras.append(f"RAINPOINT: {rainpoint_pct:.1f}%")
    if groundtruth_pct is not None:
        extras.append(f"GT: {groundtruth_pct:.1f}%")
    extra_str = (" | ".join(extras) + " | ") if extras else ""

    header = (f" EXP 10 [ETAPA 1/2 - DMRT] | {med_label} | {extra_str}"
              f"Leitura {reading_counter:04d}/{target_readings:04d} ({pct:.1f}%)")
    divider = "+" + "-" * 20 + "+" + "-" * 12 + "+" + "-" * 26 + "+" + "-" * 11 + "+" + "-" * 12 + "+" + "-" * 13 + "+" + "-" * 15 + "+"

    print("\n" + "=" * 118)
    print(f"{header:<118}")
    print("=" * 118)
    print(divider)
    print(f"| {'Medição / Par':<18} | {'Função':<10} | {'Código EPC':<24} | {'RSSI':<9} | {'Raw MRT':<10} | {'Filt. MRT':<11} | {'MRT Médio Acum':<13} |")
    print(divider)

    short_code = f"{med_label[:11]} ({pair_label})"[:18]
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


def print_table_rssi_fixed(
    rssi_counter: int,
    target_rssi_readings: int,
    fixed_power: float,
    med_label: str,
    pair_label: str,
    sensing_epc: str,
    reference_epc: str,
    last_sens_rssi: Optional[float],
    last_ref_rssi: Optional[float],
    sens_rssi_26_hist: List[float],
    ref_rssi_26_hist: List[float],
    drssi_26_hist: List[float],
):
    """Exibe tabela no terminal durante a Etapa 2 (+200 leituras de RSSI a 26 dBi fixos)."""
    pct = (rssi_counter / target_rssi_readings) * 100.0
    s_mean, s_std, s_min, s_max = calculate_stats(sens_rssi_26_hist)
    r_mean, r_std, r_min, r_max = calculate_stats(ref_rssi_26_hist)
    d_mean, d_std, _, _ = calculate_stats(drssi_26_hist)

    header = (
        f" EXP 10 [ETAPA 2/2 - RSSI FIXO @ {fixed_power:.0f} dBi] | {med_label} (Par {pair_label}) | "
        f"Leitura {rssi_counter:04d}/{target_rssi_readings:04d} ({pct:.1f}%)"
    )
    divider = "+" + "-" * 14 + "+" + "-" * 26 + "+" + "-" * 14 + "+" + "-" * 18 + "+" + "-" * 15 + "+" + "-" * 22 + "+"

    print("\n" + "=" * 116)
    print(f"{header:<116}")
    print("=" * 116)
    print(divider)
    print(f"| {'Função':<12} | {'Código EPC':<24} | {'RSSI Atual':<12} | {'RSSI Médio (±σ)':<16} | {'Mín / Máx':<13} | {'Detecções @ 26dBi':<20} |")
    print(divider)

    s_curr_str = fmt_rssi(last_sens_rssi) if last_sens_rssi is not None else "MISS"
    r_curr_str = fmt_rssi(last_ref_rssi) if last_ref_rssi is not None else "MISS"
    s_mean_str = f"{s_mean:.1f} ± {s_std:.2f}" if sens_rssi_26_hist else "N/A"
    r_mean_str = f"{r_mean:.1f} ± {r_std:.2f}" if ref_rssi_26_hist else "N/A"
    s_minmax_str = f"{s_min:.0f}/{s_max:.0f} dBm" if sens_rssi_26_hist else "N/A"
    r_minmax_str = f"{r_min:.0f}/{r_max:.0f} dBm" if ref_rssi_26_hist else "N/A"
    s_det_str = f"{len(sens_rssi_26_hist)}/{rssi_counter} ({len(sens_rssi_26_hist)/max(rssi_counter,1)*100:.1f}%)"
    r_det_str = f"{len(ref_rssi_26_hist)}/{rssi_counter} ({len(ref_rssi_26_hist)/max(rssi_counter,1)*100:.1f}%)"

    print(f"| {'Sensor':<12} | {sensing_epc:<24} | {s_curr_str:<12} | {s_mean_str:<16} | {s_minmax_str:<13} | {s_det_str:<20} |")
    print(f"| {'Referência':<12} | {reference_epc:<24} | {r_curr_str:<12} | {r_mean_str:<16} | {r_minmax_str:<13} | {r_det_str:<20} |")
    print(divider)
    drssi_str = f"{d_mean:+.2f} dB (± {d_std:.2f} dB)" if drssi_26_hist else "N/A"
    print(f" 📶 ΔRSSI @ {fixed_power:.0f} dBi (Sens - Ref) Médio Acumulado: {drssi_str}")


# ===================================================================================
# Exportação dos Dados Individuais (CSV de DMRT + CSV de RSSI @ 26 dBi + Gráfico Individual)
# ===================================================================================

def export_rssi_26dbm_csv(rssi_records: List[dict], rssi_csv_path: str):
    """Salva o CSV dedicado com as +200 leituras apenas de RSSI em potência fixa de 26 dBi."""
    if not rssi_records:
        return
    os.makedirs(os.path.dirname(os.path.abspath(rssi_csv_path)), exist_ok=True)
    fieldnames = [
        "reading",
        "elapsed_seconds",
        "power_dbm",
        "par_tags",
        "position",
        "moisture_pct",
        "groundtruth_pct",
        "sensing_rssi_26dbm",
        "ref_rssi_26dbm",
        "drssi_26dbm",
    ]
    with open(rssi_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rssi_records)
    print(f"📊 CSV de RSSI (26 dBi) exportado: {os.path.abspath(rssi_csv_path)}")


def merge_rssi_26dbm_into_individual_csv(
    ind_csv_path: str,
    rssi_records: List[dict],
    pair_label: str,
    gt_val: Optional[float] = None
):
    """
    Adiciona as colunas par_tags, groundtruth_pct (se disponível) e as 200 leituras de
    RSSI em potência fixa (sensing_rssi_26dbm, ref_rssi_26dbm, drssi_26dbm) ao CSV
    individual de resultados da medição.
    """
    if not ind_csv_path or not os.path.exists(ind_csv_path):
        return
    try:
        with open(ind_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)

        extra_cols = ["par_tags", "sensing_rssi_26dbm", "ref_rssi_26dbm", "drssi_26dbm"]
        if gt_val is not None and "groundtruth_pct" not in fieldnames:
            extra_cols.insert(1, "groundtruth_pct")

        for col in extra_cols:
            if col not in fieldnames:
                fieldnames.append(col)

        max_len = max(len(rows), len(rssi_records))
        merged_rows: List[dict] = []
        for i in range(max_len):
            base_row = dict(rows[i]) if i < len(rows) else {"second": i + 1, "position": pair_label}
            base_row["par_tags"] = pair_label
            if gt_val is not None:
                base_row["groundtruth_pct"] = f"{gt_val:.2f}"
            if i < len(rssi_records):
                r_rec = rssi_records[i]
                base_row["sensing_rssi_26dbm"] = r_rec.get("sensing_rssi_26dbm")
                base_row["ref_rssi_26dbm"] = r_rec.get("ref_rssi_26dbm")
                base_row["drssi_26dbm"] = r_rec.get("drssi_26dbm")
            merged_rows.append(base_row)

        with open(ind_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(merged_rows)
    except Exception as e:
        print(f"⚠️ Aviso ao mesclar colunas de RSSI 26 dBi no CSV {ind_csv_path}: {e}")


def export_exp10_individual_chart(
    dmrt_records: List[dict],
    rssi_records: List[dict],
    chart_filename: str,
    title_prefix: str,
    fixed_power: float = 26.0
) -> Optional[str]:
    """
    Gera o gráfico individual de uma medição contendo:
      - Painel 1: MRT (Bruto e Filtrado EMA) nas 200 leituras da Etapa 1
      - Painel 2: DMRT (Sensoriamento - Referência) nas 200 leituras da Etapa 1
      - Painel 3: RSSI durante a varredura de DMRT (Etapa 1)
      - Painel 4: RSSI com potência fixa em 26 dBi (+200 leituras da Etapa 2)
    (Nota: Não gera gráfico de curva consolidado entre diferentes medições.)
    """
    if not dmrt_records and not rssi_records:
        return None

    os.makedirs(os.path.dirname(os.path.abspath(chart_filename)), exist_ok=True)
    filepath = os.path.abspath(chart_filename)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(11, 12), dpi=150)

        # Dados da Etapa 1 (DMRT)
        sec_s_raw = [r["second"] for r in dmrt_records if r.get("sensing_raw_mrt") is not None]
        s_raw = [r["sensing_raw_mrt"] for r in dmrt_records if r.get("sensing_raw_mrt") is not None]
        sec_s_filt = [r["second"] for r in dmrt_records if r.get("sensing_filt_mrt") is not None]
        s_filt = [r["sensing_filt_mrt"] for r in dmrt_records if r.get("sensing_filt_mrt") is not None]

        sec_r_raw = [r["second"] for r in dmrt_records if r.get("ref_raw_mrt") is not None]
        r_raw = [r["ref_raw_mrt"] for r in dmrt_records if r.get("ref_raw_mrt") is not None]
        sec_r_filt = [r["second"] for r in dmrt_records if r.get("ref_filt_mrt") is not None]
        r_filt = [r["ref_filt_mrt"] for r in dmrt_records if r.get("ref_filt_mrt") is not None]

        sec_dmrt = [r["second"] for r in dmrt_records if r.get("dmrt") is not None]
        val_dmrt = [r["dmrt"] for r in dmrt_records if r.get("dmrt") is not None]

        sec_s_rssi = [r["second"] for r in dmrt_records if r.get("sensing_rssi") is not None]
        s_rssi = [r["sensing_rssi"] for r in dmrt_records if r.get("sensing_rssi") is not None]
        sec_r_rssi = [r["second"] for r in dmrt_records if r.get("ref_rssi") is not None]
        r_rssi = [r["ref_rssi"] for r in dmrt_records if r.get("ref_rssi") is not None]

        # Painel 1: MRT
        if sec_s_raw:
            ax1.plot(sec_s_raw, s_raw, color="#9ecae1", linestyle="--", linewidth=1, label="Sensoriamento (Bruto)")
        if sec_s_filt:
            ax1.plot(sec_s_filt, s_filt, color="#1f77b4", linestyle="-", linewidth=2, label="Sensoriamento (Filtrado)")
            mean_mrt = sum(s_filt) / len(s_filt)
            ax1.axhline(mean_mrt, color="#08519c", linestyle=":", linewidth=1.5, label=f"MRT Médio ({mean_mrt:.2f} dBm)")
        if sec_r_raw:
            ax1.plot(sec_r_raw, r_raw, color="#fdd0a2", linestyle="--", linewidth=1, label="Referência (Bruto)")
        if sec_r_filt:
            ax1.plot(sec_r_filt, r_filt, color="#ff7f0e", linestyle="-", linewidth=2, label="Referência (Filtrado)")
        ax1.set_title(f"{title_prefix} - DMRT (200 Leituras) + RSSI @ {fixed_power:.0f} dBi (+200 Leituras)", fontsize=12, fontweight="bold", pad=10)
        ax1.set_ylabel("MRT (dBm)", fontsize=10)
        ax1.grid(True, linestyle="--", alpha=0.5)
        ax1.legend(loc="upper right", fontsize=8, frameon=True)

        # Painel 2: DMRT
        if sec_dmrt:
            mean_d = sum(val_dmrt) / len(val_dmrt)
            ax2.plot(sec_dmrt, val_dmrt, color="#2ca02c", linestyle="-", linewidth=2, label="DMRT (Sensoriamento - Referência)")
            ax2.axhline(mean_d, color="#006d2c", linestyle=":", linewidth=1.5, label=f"DMRT Médio ({mean_d:+.2f} dB)")
            ax2.legend(loc="upper right", fontsize=8, frameon=True)
        ax2.set_ylabel("DMRT (dB)", fontsize=10)
        ax2.grid(True, linestyle="--", alpha=0.5)

        # Painel 3: RSSI no Limiar MRT (Etapa 1)
        if sec_s_rssi:
            mean_rssi = sum(s_rssi) / len(s_rssi)
            ax3.plot(sec_s_rssi, s_rssi, color="#1f77b4", linestyle="-", linewidth=1.5, label=f"Sensor RSSI no MRT (Médio: {mean_rssi:.1f} dBm)")
        if sec_r_rssi:
            mean_ref_rssi = sum(r_rssi) / len(r_rssi)
            ax3.plot(sec_r_rssi, r_rssi, color="#ff7f0e", linestyle="-", linewidth=1.5, label=f"Ref RSSI no MRT (Médio: {mean_ref_rssi:.1f} dBm)")
        ax3.set_ylabel("RSSI Varredura (dBm)", fontsize=10)
        ax3.grid(True, linestyle="--", alpha=0.5)
        if sec_s_rssi or sec_r_rssi:
            ax3.legend(loc="upper right", fontsize=8, frameon=True)

        # Painel 4: RSSI com Potência Fixa em 26 dBi (+200 leituras da Etapa 2)
        sec_s_26 = [r["reading"] for r in rssi_records if r.get("sensing_rssi_26dbm") is not None]
        s_26 = [r["sensing_rssi_26dbm"] for r in rssi_records if r.get("sensing_rssi_26dbm") is not None]
        sec_r_26 = [r["reading"] for r in rssi_records if r.get("ref_rssi_26dbm") is not None]
        r_26 = [r["ref_rssi_26dbm"] for r in rssi_records if r.get("ref_rssi_26dbm") is not None]

        if sec_s_26:
            mean_s26 = sum(s_26) / len(s_26)
            ax4.plot(sec_s_26, s_26, color="#1f77b4", linestyle="-", linewidth=1.6, label=f"Sensor RSSI @ {fixed_power:.0f} dBi (Médio: {mean_s26:.1f} dBm)")
            ax4.axhline(mean_s26, color="#08519c", linestyle=":", linewidth=1.4)
        if sec_r_26:
            mean_r26 = sum(r_26) / len(r_26)
            ax4.plot(sec_r_26, r_26, color="#ff7f0e", linestyle="-", linewidth=1.6, label=f"Ref RSSI @ {fixed_power:.0f} dBi (Médio: {mean_r26:.1f} dBm)")
            ax4.axhline(mean_r26, color="#e6550d", linestyle=":", linewidth=1.4)
        ax4.set_xlabel("Leitura / Amostra (#)", fontsize=10)
        ax4.set_ylabel(f"RSSI @ {fixed_power:.0f} dBi (dBm)", fontsize=10)
        ax4.grid(True, linestyle="--", alpha=0.5)
        if sec_s_26 or sec_r_26:
            ax4.legend(loc="upper right", fontsize=8, frameon=True)

        plt.tight_layout()
        plt.savefig(filepath, format="png", bbox_inches="tight")
        plt.close()
        print(f"📈 Gráfico individual da medição exportado: {filepath}")
        return filepath
    except Exception as e:
        print(f"⚠️ Aviso ao gerar gráfico individual com Matplotlib: {e}")
        return None


# ===================================================================================
# Compilação das Medições no CSV Consolidado (experimento_10/consolidado_exp10.csv)
# ===================================================================================

def read_consolidated_list(csv_path: str = CONSOLIDATED_CSV) -> List[dict]:
    """Lê todas as linhas do CSV consolidado preservando a ordem livre de execução."""
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
    uma nova linha ao final do consolidado_exp10.csv, preservando qualquer ordem de execução.
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


# ===================================================================================
# Status Consolidado do Experimento 10
# ===================================================================================

def show_experiment_status():
    """Exibe a tabela com todas as medições registradas no Experimento 10 (na ordem executada)."""
    records = read_consolidated_list(CONSOLIDATED_CSV)

    print("\n" + "=" * 146)
    print("            STATUS DO EXPERIMENTO 10: 200 LEITURAS DE DMRT + 200 LEITURAS DE RSSI @ 26 dBi (PARES 09-01 A 09-18)")
    print("=" * 146)
    print(f"| {'#':<3} | {'Nome / Medição':<22} | {'Par':<6} | {'DMRT Det.':<9} | {'DMRT Médio (±σ)':<18} | "
          f"{'MRT Sens':<10} | {'MRT Ref':<9} | {'RSSI@26 Sens (±σ)':<19} | {'RSSI@26 Ref (±σ)':<18} | {'ΔRSSI@26':<10} |")
    sep = ("+" + "-" * 5 + "+" + "-" * 24 + "+" + "-" * 8 + "+" + "-" * 11 + "+" + "-" * 20
           + "+" + "-" * 12 + "+" + "-" * 11 + "+" + "-" * 21 + "+" + "-" * 20 + "+" + "-" * 12 + "+")
    print(sep)

    if not records:
        print(f"| {'Nenhuma medição registrada ainda em ' + CONSOLIDATED_CSV:<142} |")
        print(sep)
        print("=" * 146 + "\n")
        return

    for idx, r in enumerate(records, start=1):
        nome = str(r.get("nome_medicao") or r.get("medicao_codigo") or f"medicao_{idx:02d}")[:22]
        par = str(r.get("par_tags") or "-")[:6]
        dmrt_val = to_float(r.get("dmrt_medio"))
        dmrt_std = to_float(r.get("dmrt_std"))
        sens_val = to_float(r.get("sensing_mrt_filt_medio"))
        ref_val = to_float(r.get("ref_mrt_filt_medio"))

        s_rssi26 = to_float(r.get("sensing_rssi_26dbm_medio"))
        s_rssi26_std = to_float(r.get("sensing_rssi_26dbm_std"))
        r_rssi26 = to_float(r.get("ref_rssi_26dbm_medio"))
        r_rssi26_std = to_float(r.get("ref_rssi_26dbm_std"))
        drssi26 = to_float(r.get("drssi_26dbm_medio"))

        leit_str = f"{r.get('leituras_detectadas_dmrt', '0')}/{r.get('leituras_planejadas', '200')}"
        dmrt_str = f"{dmrt_val:+.2f} ± {(dmrt_std or 0.0):.2f} dB" if dmrt_val is not None else "N/A"
        sens_str = f"{sens_val:.2f} dBm" if sens_val is not None else "-"
        ref_str = f"{ref_val:.2f} dBm" if ref_val is not None else "-"
        s_r26_str = f"{s_rssi26:.1f} ± {(s_rssi26_std or 0.0):.2f} dBm" if s_rssi26 is not None else "N/A"
        r_r26_str = f"{r_rssi26:.1f} ± {(r_rssi26_std or 0.0):.2f} dBm" if r_rssi26 is not None else "N/A"
        dr26_str = f"{drssi26:+.2f} dB" if drssi26 is not None else "-"

        print(f"| {idx:02d}  | {nome:<22} | {par:<6} | {leit_str:<9} | {dmrt_str:<18} | "
              f"{sens_str:<10} | {ref_str:<9} | {s_r26_str:<19} | {r_r26_str:<18} | {dr26_str:<10} |")

    print(sep)
    print(f"Total de medições registradas: {len(records)} | Arquivo compilado: {CONSOLIDATED_CSV}")
    print("=" * 146 + "\n")


# ===================================================================================
# Argumentos de Linha de Comando e Resolução de Par/Medição
# ===================================================================================

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Experimento 10: 200 leituras de DMRT + 200 leituras de RSSI fixo a 26 dBi (Pares 09-01 a 09-18)"
    )
    parser.add_argument(
        "nome_pos", nargs="*", default=[],
        help="Código do par (ex: 09-01, 9-05, 1..18) ou nome livre da medição (ex: xp-fin-100-4)"
    )
    parser.add_argument(
        "--par", "-p", "--setup",
        dest="par_tags", type=str, default=None,
        help="Escolhe o par de tags de anotacoes.md: 09-01 a 09-18 (ou 1 a 18)"
    )
    parser.add_argument(
        "--nome", "-n", "--medicao", "-m", "--etapa", "--amostra", "--name",
        dest="nome_medicao", type=str, default=None,
        help="Nome ou identificação da medição (ex: --nome xp-fin-100-4 ou -n 09-04)"
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
        help=f"Quantidade de leituras de DMRT na Etapa 1 (padrão: {DEFAULT_TARGET_READINGS})"
    )
    parser.add_argument(
        "--rssi-readings", type=int, default=DEFAULT_RSSI_READINGS,
        help=f"Quantidade de leituras adicionais apenas de RSSI na Etapa 2 (padrão: {DEFAULT_RSSI_READINGS})"
    )
    parser.add_argument(
        "--rssi-power", type=float, default=DEFAULT_FIXED_RSSI_POWER,
        help=f"Potência fixa do leitor na Etapa 2 de RSSI em dBi/dBm (padrão: {DEFAULT_FIXED_RSSI_POWER} dBi)"
    )
    parser.add_argument("--dwell", type=float, default=0.12, help="Tempo de permanência RF por nível em segundos (padrão: 0.12s)")
    parser.add_argument("--power-step", type=float, default=1.0, help="Passo de potência em dBm (padrão: 1.0 dBm)")
    parser.add_argument("--min-power", type=float, default=15.0, help="Potência mínima em dBm (padrão: 15.0 dBm)")
    parser.add_argument("--max-power", type=float, default=26.0, help="Potência máxima em dBm (padrão: 26.0 dBm)")
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Porta serial do leitor (padrão: /dev/ttyUSB0)")
    parser.add_argument("--baudrate", type=int, default=115200, help="Baudrate da porta serial (padrão: 115200)")
    parser.add_argument("--md", default=DEFAULT_MD_FILE, help=f"Arquivo markdown do experimento (padrão: {DEFAULT_MD_FILE})")
    parser.add_argument("--tag", default=None, help="Sobrescreve o EPC da Tag de Sensoriamento (24 caracteres hex)")
    parser.add_argument("--ref", default=None, help="Sobrescreve o EPC da Tag de Referência (24 caracteres hex)")
    parser.add_argument(
        "--set-tag", nargs=3, metavar=("PAR", "EPC_SENS", "EPC_REF"), default=None,
        help="Atualiza permanentemente os EPCs de um par (09-01 a 09-18) em anotacoes.md e tags_mapeadas.json"
    )
    parser.add_argument(
        "--tags", "--listar-tags", dest="listar_tags", action="store_true",
        help="Lista os 18 pares de tags (09-01 a 09-18) configurados e encerra"
    )
    parser.add_argument("--simulado", action="store_true", help="Executa em modo simulador sem hardware físico do leitor")
    parser.add_argument("--status", action="store_true", help="Exibe a tabela consolidada das medições e encerra")
    return parser.parse_args()


def resolve_measurement_and_tags(args) -> Tuple[str, str, str, str]:
    """
    Resolve de forma flexível e sem ordem fixa:
      - raw_name    : Nome da medição
      - pair_label  : Identificador do par ('09-01'..'09-18' ou 'custom')
      - sensing_epc : EPC da Tag de Sensoriamento (24 hex)
      - ref_epc     : EPC da Tag de Referência (24 hex)
    """
    pairs = get_effective_tag_pairs()

    # 1. Verifica o nome informado via flag ou argumento posicional
    raw_name: Optional[str] = None
    if args.nome_medicao and args.nome_medicao.strip():
        raw_name = args.nome_medicao.strip()
    elif args.nome_pos:
        joined = " ".join(args.nome_pos).strip()
        if joined:
            raw_name = joined

    # 2. Tenta identificar o par de tags (09-01 a 09-18)
    pair_key = normalize_pair_id(args.par_tags) if args.par_tags else None
    if not pair_key and raw_name:
        pair_key = infer_pair_from_name(raw_name)

    # 3. Se não foi passado par nem tags via CLI e o terminal é interativo, pergunta ao usuário
    is_tty = sys.stdin is not None and sys.stdin.isatty()
    if not pair_key and not (args.tag and args.ref) and is_tty:
        try:
            print("\n📋 Pares de tags disponíveis em anotacoes.md: 09-01 a 09-18 (digite 1..18, 09-01..09-18, ou Enter para 09-01)")
            typed_pair = input("🏷️  Qual par de tags deseja ler agora? [09-01]: ").strip()
            if typed_pair:
                pair_key = normalize_pair_id(typed_pair) or infer_pair_from_name(typed_pair)
            if not pair_key:
                pair_key = "09-01"
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

    if not pair_key:
        pair_key = "09-01"

    # 4. Se não informou nome da medição, usa o próprio código do par (ex: 09-01) ou pergunta no terminal
    if not raw_name:
        default_name = pair_key
        if is_tty:
            try:
                typed_name = input(f"📝 Digite o nome desta medição [Enter para '{default_name}']: ").strip()
                raw_name = typed_name if typed_name else default_name
            except (EOFError, KeyboardInterrupt):
                print()
                sys.exit(0)
        else:
            raw_name = default_name

    # 5. Obtém os EPCs do par escolhido e aplica qualquer sobrescrita manual (--tag / --ref)
    base_sens, base_ref = pairs.get(pair_key, (DEFAULT_SENSING_EPC, DEFAULT_REF_EPC))
    arg_tag = args.tag.strip().upper() if args.tag else None
    arg_ref = args.ref.strip().upper() if args.ref else None

    sensing_epc = arg_tag if is_valid_hex_epc(arg_tag) else base_sens
    ref_epc = arg_ref if is_valid_hex_epc(arg_ref) else base_ref

    pair_label = pair_key
    if (arg_tag and arg_tag != base_sens) or (arg_ref and arg_ref != base_ref):
        pair_label = f"{pair_key}*"

    return raw_name, pair_label, sensing_epc.upper(), ref_epc.upper()


# ===================================================================================
# Pipeline Principal de Execução do Experimento 10
# ===================================================================================

def main():
    args = parse_arguments()

    # Modo atualização permanente de tags (--set-tag PAR EPC_SENS EPC_REF)
    if args.set_tag:
        par_id, new_sens, new_ref = args.set_tag
        update_pair_in_files(par_id, new_sens, new_ref)
        show_configured_tags()
        return

    # Modo listagem dos 18 pares de tags (--tags)
    if args.listar_tags:
        show_configured_tags()
        return

    # Modo visualização de status consolidado (--status)
    if args.status:
        show_experiment_status()
        return

    # Resolve nome da medição, par (09-01 a 09-18) e EPCs das tags
    raw_name, pair_label, sensing_epc, ref_epc = resolve_measurement_and_tags(args)
    med_slug = slugify_name(raw_name)
    med_label = format_display_name(raw_name)

    rainpoint_pct = args.umidade
    groundtruth_pct = args.groundtruth
    vaso = args.vaso.strip() if args.vaso else med_label

    csv_path = os.path.join(EXP10_DIR, f"{med_slug}_resultados.csv")
    rssi_csv_path = os.path.join(EXP10_DIR, f"{med_slug}_rssi_26dbm.csv")
    chart_path = os.path.join(EXP10_DIR, f"{med_slug}_grafico.png")
    setup_title = f"Experimento 10 - {med_label} (Par {pair_label})"

    target_readings = args.readings
    target_rssi_readings = args.rssi_readings
    fixed_rssi_power = max(15.0, min(26.0, args.rssi_power))

    # Conecta ao leitor (ou instancia Mock)
    reader = None
    if not args.simulado:
        reader = INR200Reader(port=args.port, baudrate=args.baudrate)
        if not reader.connect():
            print(f"\n❌ Não foi possível conectar ao leitor na porta {args.port}.")
            print(f"👉 Conceda permissão: sudo chmod 666 {args.port}")
            print("👉 Ou execute com flag --simulado para testar offline.")
            sys.exit(1)
    else:
        reader = MockReaderForExp10(
            port=args.port,
            baudrate=args.baudrate,
            sensing_epc=sensing_epc,
            ref_epc=ref_epc,
            moisture_pct=rainpoint_pct,
            medicao_label=f"{med_label} [{pair_label}]"
        )
        reader.connect()

    print("=" * 116)
    print("     IN-R200 UHF RFID Reader - EXPERIMENTO 10: 200 LEITURAS DMRT + 200 LEITURAS RSSI @ 26 dBi (09-01 a 09-18)")
    print("=" * 116)
    print(f"🏷️  Nome da Medição     : {med_label} (código: {med_slug})")
    print(f"🔢 Par de Tags Selecion.: {pair_label}")
    if rainpoint_pct is not None:
        print(f"💧 Umidade RainPoint   : {rainpoint_pct:.1f}%")
    if groundtruth_pct is not None:
        print(f"🧪 Ground Truth Grav.  : {groundtruth_pct:.2f}%")
    print(f"📌 Tag Sensoriamento   : {sensing_epc} (Substrato / Vaso)")
    print(f"📌 Tag Referência      : {ref_epc} (Isolada / Referência)")
    print(f"⚡ Etapa 1 (DMRT)      : {target_readings} leituras (varredura {args.min_power:.1f} a {args.max_power:.1f} dBm, passo {args.power_step} dBm)")
    print(f"📶 Etapa 2 (RSSI Fixo) : +{target_rssi_readings} leituras apenas de RSSI com potência fixa em {fixed_rssi_power:.0f} dBi ({fixed_rssi_power:.1f} dBm)")
    print(f"⏱️  Tempo Dwell/Nível  : {args.dwell:.3f} s")
    print(f"📁 Arquivo CSV Geral   : {csv_path}")
    print(f"📁 Arquivo CSV RSSI    : {rssi_csv_path}")
    print(f"📈 Gráfico Individual  : {chart_path}")
    print("=" * 116)

    mrt_calc = MRTCalculator(
        reader=reader,
        min_power=args.min_power,
        max_power=args.max_power,
        power_step=args.power_step,
        dwell_time=args.dwell
    )
    exporter = DMRTExporter()
    target_list = [sensing_epc, ref_epc]

    # Históricos da Etapa 1 (200 leituras de DMRT)
    sens_hist_raw: List[float] = []
    sens_hist_filt: List[float] = []
    sens_hist_rssi: List[float] = []
    ref_hist_raw: List[float] = []
    ref_hist_filt: List[float] = []
    ref_hist_rssi: List[float] = []
    dmrt_hist: List[float] = []

    # Históricos da Etapa 2 (+200 leituras apenas de RSSI em potência fixa de 26 dBi)
    sens_rssi_26_hist: List[float] = []
    ref_rssi_26_hist: List[float] = []
    drssi_26_hist: List[float] = []
    rssi_26_records: List[dict] = []

    reading_counter = 0
    rssi_counter = 0

    try:
        # =========================================================================
        # ETAPA 1: 200 Leituras Padrões de DMRT (Varredura de Potência)
        # =========================================================================
        print(f"\n📡 [ETAPA 1/2] Iniciando as {target_readings} leituras padrões de DMRT para '{med_label}' (Par {pair_label})...")
        print("   (Pressione Ctrl+C a qualquer momento para interromper e salvar os dados coletados)\n")

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
            print(f"  ⚡ [DMRT {reading_counter:04d}/{target_readings:04d}] {pair_label} ({med_slug}) | {s_str} | {r_str} | {d_str} | Tempo: {dt_sweep:.2f}s")

            if reading_counter % 10 == 0 or reading_counter == target_readings:
                print_table_dmrt(
                    reading_counter, target_readings, med_label, pair_label,
                    rainpoint_pct, groundtruth_pct, sensing_epc, ref_epc,
                    sens_hist_filt, sens_hist_rssi,
                    ref_hist_filt, ref_hist_rssi,
                    dmrt_hist, current_time
                )

        # =========================================================================
        # ETAPA 2: +200 Leituras Apenas do Valor de RSSI com Potência Fixa em 26 dBi
        # =========================================================================
        if target_rssi_readings > 0:
            print("\n" + "=" * 116)
            print(f"📶 [ETAPA 2/2] Leituras de DMRT concluídas! Fixando potência do leitor em {fixed_rssi_power:.0f} dBi ({fixed_rssi_power:.1f} dBm)...")
            print(f"   Iniciando +{target_rssi_readings} leituras apenas do valor de RSSI das tags ({pair_label})...")
            print("=" * 116 + "\n")

            reader.set_rf_power(fixed_rssi_power, delay=0.05)
            t_rssi_start = time.time()

            while rssi_counter < target_rssi_readings:
                rssi_counter += 1
                t_r0 = time.time()

                # Garante potência fixa em 26.0 dBm e lê apenas o RSSI das duas tags
                detected_rssi = read_tags_rssi_at_fixed_power(
                    reader=reader,
                    sensing_epc=sensing_epc,
                    ref_epc=ref_epc,
                    dwell_time=args.dwell
                )
                dt_r = time.time() - t_r0

                s_info = detected_rssi.get(sensing_epc)
                r_info = detected_rssi.get(ref_epc)

                s_rssi_val = float(s_info["rssi"]) if s_info is not None else None
                r_rssi_val = float(r_info["rssi"]) if r_info is not None else None

                if s_rssi_val is not None:
                    sens_rssi_26_hist.append(s_rssi_val)
                if r_rssi_val is not None:
                    ref_rssi_26_hist.append(r_rssi_val)

                drssi_val = None
                if s_rssi_val is not None and r_rssi_val is not None:
                    drssi_val = round(s_rssi_val - r_rssi_val, 2)
                    drssi_26_hist.append(drssi_val)

                rssi_26_records.append({
                    "reading": rssi_counter,
                    "elapsed_seconds": round(time.time() - t_rssi_start, 2),
                    "power_dbm": round(fixed_rssi_power, 1),
                    "par_tags": pair_label,
                    "position": med_slug,
                    "moisture_pct": round(rainpoint_pct, 2) if rainpoint_pct is not None else None,
                    "groundtruth_pct": round(groundtruth_pct, 2) if groundtruth_pct is not None else None,
                    "sensing_rssi_26dbm": round(s_rssi_val, 1) if s_rssi_val is not None else None,
                    "ref_rssi_26dbm": round(r_rssi_val, 1) if r_rssi_val is not None else None,
                    "drssi_26dbm": drssi_val,
                })

                s_r_str = f"S_RSSI:{fmt_rssi(s_rssi_val)}" if s_rssi_val is not None else "S_RSSI:MISS"
                r_r_str = f"R_RSSI:{fmt_rssi(r_rssi_val)}" if r_rssi_val is not None else "R_RSSI:MISS"
                dr_str = f"ΔRSSI:{drssi_val:+.1f}dB" if drssi_val is not None else "ΔRSSI:N/A"
                print(
                    f"  📶 [RSSI@{fixed_rssi_power:.0f}dBi {rssi_counter:04d}/{target_rssi_readings:04d}] "
                    f"{pair_label} ({med_slug}) | {s_r_str} | {r_r_str} | {dr_str} | Tempo: {dt_r:.2f}s"
                )

                if rssi_counter % 10 == 0 or rssi_counter == target_rssi_readings:
                    print_table_rssi_fixed(
                        rssi_counter, target_rssi_readings, fixed_rssi_power,
                        med_label, pair_label, sensing_epc, ref_epc,
                        s_rssi_val, r_rssi_val,
                        sens_rssi_26_hist, ref_rssi_26_hist, drssi_26_hist
                    )

    except KeyboardInterrupt:
        print("\n\n⏹️ Coleta interrompida pelo usuário via Ctrl+C. Salvando dados coletados até o momento...")
    finally:
        reader.set_rf_power(26.0)
        reader.close()

        os.makedirs(EXP10_DIR, exist_ok=True)
        print(f"\n📊 Exportando dados da medição para {csv_path} e {rssi_csv_path}...")
        exporter.export_csv(csv_path)
        merge_rssi_26dbm_into_individual_csv(
            ind_csv_path=csv_path,
            rssi_records=rssi_26_records,
            pair_label=pair_label,
            gt_val=groundtruth_pct
        )
        export_rssi_26dbm_csv(rssi_26_records, rssi_csv_path)
        export_exp10_individual_chart(
            dmrt_records=exporter.records,
            rssi_records=rssi_26_records,
            chart_filename=chart_path,
            title_prefix=setup_title,
            fixed_power=fixed_rssi_power
        )

        # Estatísticas da Etapa 1 (DMRT)
        s_raw_mean, s_raw_std, _, _ = calculate_stats(sens_hist_raw)
        s_filt_mean, s_filt_std, _, _ = calculate_stats(sens_hist_filt)
        s_rssi_mean, s_rssi_std, _, _ = calculate_stats(sens_hist_rssi)
        r_raw_mean, r_raw_std, _, _ = calculate_stats(ref_hist_raw)
        r_filt_mean, r_filt_std, _, _ = calculate_stats(ref_hist_filt)
        r_rssi_mean, r_rssi_std, _, _ = calculate_stats(ref_hist_rssi)
        dmrt_mean, dmrt_std, dmrt_min, dmrt_max = calculate_stats(dmrt_hist)
        has_dmrt = bool(dmrt_hist)
        executed_dmrt = max(reading_counter, 1)

        # Estatísticas da Etapa 2 (+200 leituras de RSSI @ 26 dBi)
        s_r26_mean, s_r26_std, s_r26_min, s_r26_max = calculate_stats(sens_rssi_26_hist)
        r_r26_mean, r_r26_std, r_r26_min, r_r26_max = calculate_stats(ref_rssi_26_hist)
        dr26_mean, dr26_std, _, _ = calculate_stats(drssi_26_hist)
        executed_rssi26 = max(rssi_counter, 1)

        record_entry = {
            "medicao_codigo": med_slug,
            "nome_medicao": med_label,
            "par_tags": pair_label,
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
            "taxa_deteccao_dmrt_pct": f"{(len(dmrt_hist) / executed_dmrt * 100.0):.1f}",
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
            "leituras_planejadas_rssi_26dbm": target_rssi_readings,
            "leituras_executadas_rssi_26dbm": rssi_counter,
            "leituras_detectadas_sens_rssi_26dbm": len(sens_rssi_26_hist),
            "leituras_detectadas_ref_rssi_26dbm": len(ref_rssi_26_hist),
            "taxa_deteccao_sens_rssi_26dbm_pct": f"{(len(sens_rssi_26_hist) / executed_rssi26 * 100.0):.1f}",
            "sensing_rssi_26dbm_medio": f"{s_r26_mean:.1f}" if sens_rssi_26_hist else "N/A",
            "sensing_rssi_26dbm_std": f"{s_r26_std:.2f}" if sens_rssi_26_hist else "N/A",
            "sensing_rssi_26dbm_min": f"{s_r26_min:.1f}" if sens_rssi_26_hist else "N/A",
            "sensing_rssi_26dbm_max": f"{s_r26_max:.1f}" if sens_rssi_26_hist else "N/A",
            "ref_rssi_26dbm_medio": f"{r_r26_mean:.1f}" if ref_rssi_26_hist else "N/A",
            "ref_rssi_26dbm_std": f"{r_r26_std:.2f}" if ref_rssi_26_hist else "N/A",
            "ref_rssi_26dbm_min": f"{r_r26_min:.1f}" if ref_rssi_26_hist else "N/A",
            "ref_rssi_26dbm_max": f"{r_r26_max:.1f}" if ref_rssi_26_hist else "N/A",
            "drssi_26dbm_medio": f"{dr26_mean:.2f}" if drssi_26_hist else "N/A",
            "drssi_26dbm_std": f"{dr26_std:.2f}" if drssi_26_hist else "N/A",
            "sensing_epc": sensing_epc,
            "reference_epc": ref_epc,
            "arquivo_csv": csv_path,
            "arquivo_rssi_csv": rssi_csv_path,
            "arquivo_grafico": chart_path,
            "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        upsert_consolidated_record(record_entry, CONSOLIDATED_CSV)

    dmrt_txt = f"{dmrt_mean:+.2f} dB (± {dmrt_std:.2f} dB)" if has_dmrt else "N/A"
    s_r26_txt = f"{fmt_rssi(s_r26_mean)} (± {s_r26_std:.2f} dB)" if sens_rssi_26_hist else "N/A"
    r_r26_txt = f"{fmt_rssi(r_r26_mean)} (± {r_r26_std:.2f} dB)" if ref_rssi_26_hist else "N/A"
    dr26_txt = f"{dr26_mean:+.2f} dB (± {dr26_std:.2f} dB)" if drssi_26_hist else "N/A"

    print("\n" + "=" * 116)
    print(f"        RELATÓRIO FINAL: {setup_title.upper()}")
    print("=" * 116)
    print(f"🏷️  Medição                 : {med_label} ({med_slug}) | Par: {pair_label}")
    print(f"📌 Tag Sensoriamento        : {sensing_epc} (Substrato / Vaso)")
    print(f"📌 Tag Referência           : {ref_epc} (Isolada / Referência)")
    if rainpoint_pct is not None:
        print(f"💧 Umidade RainPoint        : {rainpoint_pct:.1f}%")
    if groundtruth_pct is not None:
        print(f"🧪 Ground Truth Grav.       : {groundtruth_pct:.2f}%")
    print("-" * 116)
    print(f"🔁 Etapa 1 (Varredura DMRT) : {reading_counter} leituras realizadas ({len(dmrt_hist)} leituras válidas de DMRT)")
    if sens_hist_filt:
        print(f"🎯 Sensor MRT (EMA)         : {s_filt_mean:.2f} dBm (± {s_filt_std:.2f} dB) | RSSI no MRT: {fmt_rssi(s_rssi_mean)}")
    if ref_hist_filt:
        print(f"🎯 Referência MRT           : {r_filt_mean:.2f} dBm (± {r_filt_std:.2f} dB) | RSSI no MRT: {fmt_rssi(r_rssi_mean)}")
    print(f"⚖️  DMRT Médio (ΔMRT)       : {dmrt_txt}")
    print("-" * 116)
    print(f"📶 Etapa 2 (RSSI @ {fixed_rssi_power:.0f} dBi) : {rssi_counter} leituras realizadas (Sens: {len(sens_rssi_26_hist)} | Ref: {len(ref_rssi_26_hist)})")
    print(f"📡 Sensor RSSI @ {fixed_rssi_power:.0f} dBi     : {s_r26_txt}")
    print(f"📡 Referência RSSI @ {fixed_rssi_power:.0f} dBi : {r_r26_txt}")
    print(f"📊 ΔRSSI @ {fixed_rssi_power:.0f} dBi (S - R)   : {dr26_txt}")
    print("-" * 116)
    print(f"👉 RESULTADO [{med_label}]: DMRT = {dmrt_txt}  |  Sensor RSSI@{fixed_rssi_power:.0f}dBi = {s_r26_txt}")
    print("=" * 116)
    print(f"✅ CSV completo salvo em          : {os.path.abspath(csv_path)}")
    print(f"✅ CSV RSSI @ {fixed_rssi_power:.0f} dBi salvo em     : {os.path.abspath(rssi_csv_path)}")
    print(f"✅ Gráfico da medição salvo em    : {os.path.abspath(chart_path)}")
    print(f"✅ Dados compilados salvos em     : {os.path.abspath(CONSOLIDATED_CSV)}")
    print("=" * 116)


if __name__ == "__main__":
    main()
