#!/usr/bin/env python3
"""
===================================================================================
 Mapeador de Tags RFID UHF - Leitor IN-R200 (MagicRF M100)
===================================================================================
 Arquivo exclusivo para descoberta, identificação e mapeamento de novas tags RFID.
 
 Recursos principais:
 1. Varredura em Tempo Real: Detecta tags no campo com RSSI visual e contagem.
 2. Assistente de Par (GreenTag): Mapeia par (Sensoriamento + Referência) passo a passo.
 3. Mapeamento Individual: Identifica e rotula tags individuais.
 4. Banco Local (JSON): Persiste as tags em 'tags_mapeadas.json'.
 5. Integração Markdown: Anexa e formata automaticamente para 'anotacoes.md'.
 6. Suporte a Isolamento RF: Permite usar baixa potência (ex: 16 dBm) para aproximar
    apenas a tag desejada sem interferência de outras no ambiente.
===================================================================================
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import serial
    import serial.tools.list_ports
    from in_r200_driver import INR200Reader
except ImportError as e:
    print(f"⚠️ Erro ao importar dependências: {e}")
    print("Certifique-se de executar no ambiente virtual com pyserial instalado.")
    sys.exit(1)

# Caminhos padrão
DEFAULT_JSON_FILE = "tags_mapeadas.json"
DEFAULT_MD_FILE = "anotacoes.md"
DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 115200
DEFAULT_SCAN_POWER = 26.0
ISOLATION_POWER = 18.0


# ===================================================================================
# Utilitários de Persistência (JSON e Markdown)
# ===================================================================================

def load_database(json_path: str = DEFAULT_JSON_FILE) -> dict:
    """Carrega o banco de dados de tags mapeadas do arquivo JSON."""
    if not os.path.exists(json_path):
        return {"tags": {}, "pares": []}
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "tags" not in data:
                data["tags"] = {}
            if "pares" not in data:
                data["pares"] = []
            return data
    except Exception as e:
        print(f"⚠️ Erro ao carregar {json_path}: {e}")
        return {"tags": {}, "pares": []}


def save_database(data: dict, json_path: str = DEFAULT_JSON_FILE):
    """Salva a estrutura de dados atualizada no arquivo JSON."""
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"💾 Banco de tags atualizado em: {os.path.abspath(json_path)}")
    except Exception as e:
        print(f"❌ Erro ao salvar {json_path}: {e}")


def append_pair_to_markdown(
    md_path: str,
    setup_name: str,
    sensing_epc: str,
    reference_epc: str
):
    """
    Anexa a definição de um novo par de experimento no arquivo anotacoes.md,
    seguindo o padrão já utilizado no repositório.
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    block = (
        f"\n# {setup_name} (Mapeado em {date_str})\n"
        f"# sensoriamento - referencia\n\n"
        f"{setup_name}: {sensing_epc} - {reference_epc}\n"
    )
    try:
        with open(md_path, "a", encoding="utf-8") as f:
            f.write(block)
        print(f"📝 Par anexado com sucesso ao arquivo '{md_path}'!")
    except Exception as e:
        print(f"❌ Erro ao escrever em {md_path}: {e}")


# ===================================================================================
# Utilitários Visuais
# ===================================================================================

def format_rssi_bar(rssi_val: int) -> str:
    """
    Gera uma barra de sinal visual com base no valor RSSI.
    Suporta tanto RSSI negativo padrão (ex: -72 dBm) quanto magnitudes positivas.
    """
    dbm = rssi_val if rssi_val < 0 else -rssi_val
    clamped = max(-85, min(-30, dbm))
    pct = (clamped - (-85)) / ((-30) - (-85))
    bar_len = 10
    filled = int(round(pct * bar_len))
    bar = "█" * filled + "░" * (bar_len - filled)
    return f"[{bar}] {dbm:3d} dBm"


def print_banner():
    print("=" * 76)
    print("       🏷️  MAPEADOR DE TAGS RFID UHF - LEITOR IN-R200 (MAGICRF M100)")
    print("=" * 76)


# ===================================================================================
# Mock / Simulação (para testes ou quando o leitor físico estiver offline)
# ===================================================================================

class MockReader:
    """Simulador do INR200Reader para testes de interface e validação offline."""
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.is_reading = False
        self.power = 26.0

    def connect(self) -> bool:
        print(f"⚡ [MODO SIMULADO] Conectado virtualmente em {self.port}")
        return True

    def get_module_info(self) -> str:
        return "IN-R200 M100 V1.0 (SIMULADO)"

    def set_rf_power(self, power_dbm: float = 26.0) -> bool:
        self.power = power_dbm
        return True

    def start_inventory(self, tag_callback):
        self.is_reading = True
        import threading
        def _mock_loop():
            fake_tags = [
                ("E2806995000050136FD09D75", 42, "3400"),
                ("E2806995000050136FD0A175", 46, "3400"),
                ("E28011912000789012345678", 55, "3400"),
            ]
            idx = 0
            while self.is_reading:
                epc, rssi, pc = fake_tags[idx % len(fake_tags)]
                tag_callback(epc, rssi + (idx % 3), pc)
                idx += 1
                time.sleep(0.3)
        self._thread = threading.Thread(target=_mock_loop, daemon=True)
        self._thread.start()

    def stop_inventory(self):
        self.is_reading = False

    def close(self):
        self.stop_inventory()


# ===================================================================================
# Conexão e Inicialização do Leitor
# ===================================================================================

def init_reader(port: str, baudrate: int, power: float, mock: bool = False):
    """Instancia, conecta e configura a potência inicial do leitor."""
    if mock:
        reader = MockReader(port=port, baudrate=baudrate)
    else:
        reader = INR200Reader(port=port, baudrate=baudrate)

    if not reader.connect():
        print(f"\n❌ Falha ao conectar ao leitor na porta '{port}'.")
        print("\n💡 Possíveis causas e soluções:")
        print("  1. Verifique se o cabo USB do leitor está conectado ao computador.")
        print("  2. Conceda permissão à porta serial:")
        print(f"     sudo chmod 666 {port}")
        print("     ou torne permanente: sudo usermod -aG dialout $USER")
        print("  3. Verifique outras portas disponíveis:")
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            print(f"     - {p.device} ({p.description})")
        print("  4. Se quiser apenas testar a ferramenta sem hardware físico, use --simulado.\n")
        return None

    reader.set_rf_power(power)
    return reader


# ===================================================================================
# Modo 1: Varredura em Tempo Real
# ===================================================================================

def run_live_scan(reader, json_path: str = DEFAULT_JSON_FILE, duration: Optional[float] = None):
    """
    Executa varredura contínua das tags presentes no campo de RF.
    Exibe tabela ao vivo com EPC, RSSI visual, quantidade de leituras e apelidos salvos.
    """
    db = load_database(json_path)
    registered = db.get("tags", {})

    detected: Dict[str, dict] = {}
    print("\n📡 Iniciando Varredura em Tempo Real...")
    print("   Pressione Ctrl+C para pausar/finalizar e nomear tags.\n")

    def _on_tag(epc: str, rssi: int, pc: str):
        now = time.time()
        is_new = epc not in detected
        if is_new:
            detected[epc] = {
                "count": 1,
                "rssi": rssi,
                "pc": pc,
                "first_seen": now,
                "last_seen": now
            }
            alias = registered.get(epc, {}).get("nome", "Não cadastrada")
            funcao = registered.get(epc, {}).get("funcao", "")
            role_tag = f"[{funcao.upper()}] " if funcao else ""
            sinal_str = f"{rssi} dBm" if rssi < 0 else f"-{rssi} dBm"
            print(f" ✨ [NOVA TAG DETECTADA] {epc} | {role_tag}{alias} | Sinal: {sinal_str}")
        else:
            detected[epc]["count"] += 1
            detected[epc]["rssi"] = rssi
            detected[epc]["last_seen"] = now

    reader.start_inventory(_on_tag)
    start_time = time.time()

    try:
        while True:
            time.sleep(1.0)
            elapsed = time.time() - start_time
            if duration and elapsed >= duration:
                break
            # Exibe status periódico sucinto se houver tags
            if detected:
                total_reads = sum(t["count"] for t in detected.values())
                print(f" ⏳ [{elapsed:4.0f}s] Tags ativas no campo: {len(detected)} | Total de leituras: {total_reads}", end="\r")
    except KeyboardInterrupt:
        print("\n\n⏹️ Varredura finalizada pelo usuário.")
    finally:
        reader.stop_inventory()

    # Relatório das tags detectadas
    print("\n" + "=" * 90)
    print(f"                     RESUMO DAS TAGS DETECTADAS ({len(detected)} encontradas)")
    print("=" * 90)
    print(f"| {'#':<3} | {'Código EPC':<26} | {'Sinal RSSI':<22} | {'Leituras':<9} | {'Cadastro / Apelido':<20} |")
    print("+" + "-"*5 + "+" + "-"*28 + "+" + "-"*24 + "+" + "-"*11 + "+" + "-"*22 + "+")

    # Ordena pelo sinal mais forte (maior RSSI algébrico, ex: -40 dBm antes de -80 dBm)
    sorted_tags = sorted(detected.items(), key=lambda item: item[1]["rssi"] if item[1]["rssi"] < 0 else -item[1]["rssi"], reverse=True)
    for idx, (epc, info) in enumerate(sorted_tags, start=1):
        rssi_bar = format_rssi_bar(info["rssi"])
        alias = registered.get(epc, {}).get("nome", "—")
        funcao = registered.get(epc, {}).get("funcao", "")
        if funcao:
            alias = f"[{funcao[:3].upper()}] {alias}"
        print(f"| {idx:<3} | {epc:<26} | {rssi_bar:<22} | {info['count']:<9} | {alias[:20]:<20} |")
    print("+" + "-"*5 + "+" + "-"*28 + "+" + "-"*24 + "+" + "-"*11 + "+" + "-"*22 + "+")

    # Opção interativa para salvar qualquer uma das tags detectadas
    if detected:
        ask_save = input("\n💾 Deseja cadastrar/renomear alguma dessas tags agora? (s/N): ").strip().lower()
        if ask_save == 's':
            while True:
                escolha = input(f"Digite o número da tag (1-{len(sorted_tags)}) ou '0' para sair: ").strip()
                if escolha == '0' or not escolha:
                    break
                try:
                    num = int(escolha)
                    if 1 <= num <= len(sorted_tags):
                        target_epc = sorted_tags[num - 1][0]
                        prompt_and_save_tag(target_epc, db, json_path)
                    else:
                        print("Opção inválida.")
                except ValueError:
                    print("Por favor, digite um número válido.")


# ===================================================================================
# Modo 2: Assistente Guiado: Mapear Par de Experimento (GreenTag / DMRT)
# ===================================================================================

def run_pair_wizard(reader, json_path: str = DEFAULT_JSON_FILE, md_path: str = DEFAULT_MD_FILE):
    """
    Assistente guiado passo a passo para cadastrar um par de tags:
    - 1 Tag de Sensoriamento (inferior / área sujeita à umidade/solo)
    - 1 Tag de Referência (superior / controle)
    """
    print_banner()
    print("🎯 ASSISTENTE DE MAPEAMENTO DE PAR (SENSORIAMENTO + REFERÊNCIA)")
    print("-" * 76)
    print("DICA: Para facilitar a identificação da tag correta sem interferências,")
    print("      o assistente pode reduzir temporariamente a potência do leitor para")
    print("      que apenas a tag aproximada da antena seja capturada.")
    print("-" * 76)

    usar_baixa_potencia = input(f"Deseja usar potência reduzida ({ISOLATION_POWER} dBm) para isolamento? (S/n): ").strip().lower() != 'n'
    test_power = ISOLATION_POWER if usar_baixa_potencia else DEFAULT_SCAN_POWER
    reader.set_rf_power(test_power)
    print(f"⚡ Potência ajustada para {test_power:.1f} dBm.\n")

    db = load_database(json_path)

    # -------------------------------------------------------------------------------
    # PASSO 1: Tag de Sensoriamento
    # -------------------------------------------------------------------------------
    print("┌" + "─" * 74 + "┐")
    print("│ PASSO 1: TAG DE SENSORIAMENTO (INFERIOR)                                 │")
    print("│ Aproxime APENAS a Tag de Sensoriamento da antena...                      │")
    print("└" + "─" * 74 + "┘")
    input("Pressione [ENTER] quando estiver pronto para iniciar a leitura...")

    sensing_epc = capture_single_tag(reader, "Sensoriamento")
    if not sensing_epc:
        print("❌ Operação cancelada ou nenhuma tag detectada.")
        reader.set_rf_power(DEFAULT_SCAN_POWER)
        return

    print(f"✅ Tag de Sensoriamento definida: {sensing_epc}\n")

    # -------------------------------------------------------------------------------
    # PASSO 2: Tag de Referência
    # -------------------------------------------------------------------------------
    print("┌" + "─" * 74 + "┐")
    print("│ PASSO 2: TAG DE REFERÊNCIA (SUPERIOR)                                    │")
    print("│ Afaste a anterior e aproxime APENAS a Tag de Referência da antena...     │")
    print("└" + "─" * 74 + "┘")
    input("Pressione [ENTER] quando estiver pronto para iniciar a leitura...")

    reference_epc = capture_single_tag(reader, "Referência", exclude_epc=sensing_epc)
    if not reference_epc:
        print("❌ Operação cancelada ou nenhuma tag detectada.")
        reader.set_rf_power(DEFAULT_SCAN_POWER)
        return

    print(f"✅ Tag de Referência definida: {reference_epc}\n")

    # Restaura potência padrão
    reader.set_rf_power(DEFAULT_SCAN_POWER)

    # -------------------------------------------------------------------------------
    # PASSO 3: Identificação do Setup / Experimento
    # -------------------------------------------------------------------------------
    print("┌" + "─" * 74 + "┐")
    print("│ PASSO 3: IDENTIFICAÇÃO DO SETUP / EXPERIMENTO                            │")
    print("└" + "─" * 74 + "┘")
    sugestao_nome = f"Experimento {len(db.get('pares', [])) + 1}"
    nome_exp = input(f"Informe o nome/título do setup [Padrão: {sugestao_nome}]: ").strip()
    if not nome_exp:
        nome_exp = sugestao_nome

    obs = input("Observações adicionais (ex: solo turfa 500g, 40cm antena): ").strip()
    hoje = datetime.now().strftime("%Y-%m-%d")

    # Salva no banco JSON
    db["tags"][sensing_epc] = {
        "nome": f"{nome_exp} - Sensoriamento",
        "funcao": "sensoriamento",
        "setup": nome_exp,
        "observacoes": obs,
        "data_cadastro": hoje
    }
    db["tags"][reference_epc] = {
        "nome": f"{nome_exp} - Referência",
        "funcao": "referencia",
        "setup": nome_exp,
        "observacoes": obs,
        "data_cadastro": hoje
    }
    db["pares"].append({
        "experimento": nome_exp,
        "sensoriamento": sensing_epc,
        "referencia": reference_epc,
        "observacoes": obs,
        "data_cadastro": hoje
    })
    save_database(db, json_path)

    # -------------------------------------------------------------------------------
    # PASSO 4: Formatação e Anexação em Markdown
    # -------------------------------------------------------------------------------
    print("\n" + "=" * 76)
    print("🎉 MAPEAMENTO CONCLUÍDO COM SUCESSO!")
    print("=" * 76)
    print(f"📌 Experimento       : {nome_exp}")
    print(f"🏷️  Tag Sensoriamento : {sensing_epc}")
    print(f"🏷️  Tag Referência    : {reference_epc}")
    if obs:
        print(f"📝 Observações       : {obs}")
    print("=" * 76)

    print("\n📋 Formato pronto para arquivos Markdown (.md) ou 'anotacoes.md':")
    md_snippet = (
        f"# {nome_exp}\n"
        f"# sensoriamento - referencia\n\n"
        f"{nome_exp}: {sensing_epc} - {reference_epc}\n"
    )
    print("-" * 50)
    print(md_snippet.strip())
    print("-" * 50)

    anexar = input(f"\nDeseja anexar automaticamente este par ao arquivo '{md_path}'? (S/n): ").strip().lower()
    if anexar != 'n':
        append_pair_to_markdown(md_path, nome_exp, sensing_epc, reference_epc)


def capture_single_tag(reader, label: str, exclude_epc: Optional[str] = None) -> Optional[str]:
    """
    Inicia varredura temporária até capturar tags, filtrando o sinal mais forte.
    Permite confirmação visual pelo usuário.
    """
    detected: Dict[str, dict] = {}
    print(f"🔍 Procurando tag de {label}... (Aproxime a tag)")

    def _cb(epc: str, rssi: int, pc: str):
        if exclude_epc and epc == exclude_epc:
            return
        if epc not in detected:
            detected[epc] = {"rssi": rssi, "count": 1}
            print(f"  ⚡ Sinal detectado: {epc} ({format_rssi_bar(rssi)})")
        else:
            detected[epc]["count"] += 1
            detected[epc]["rssi"] = rssi

    reader.start_inventory(_cb)
    time_limit = 15.0
    start = time.time()

    try:
        while (time.time() - start) < time_limit:
            if detected:
                # Verifica se a tag mais forte tem ao menos 3 leituras consistentes
                strongest = max(detected.items(), key=lambda x: x[1]["rssi"] if x[1]["rssi"] < 0 else -x[1]["rssi"])
                if strongest[1]["count"] >= 3:
                    break
            time.sleep(0.2)
    finally:
        reader.stop_inventory()

    if not detected:
        print("⚠️ Nenhuma tag detectada no intervalo de tempo.")
        return None

    # Seleciona a tag com maior sinal (RSSI mais alto)
    strongest_epc, info = max(detected.items(), key=lambda x: x[1]["rssi"] if x[1]["rssi"] < 0 else -x[1]["rssi"])
    print(f"\n🎯 Tag com sinal mais forte identificada:")
    print(f"   EPC: {strongest_epc}")
    print(f"   Sinal: {format_rssi_bar(info['rssi'])} (Leituras: {info['count']})")

    confirma = input(f"Confirmar esta tag como {label}? (S/n): ").strip().lower()
    if confirma == 'n':
        return None
    return strongest_epc


# ===================================================================================
# Modo 3: Mapear / Nomear Tag Individual
# ===================================================================================

def run_single_tag_wizard(reader, json_path: str = DEFAULT_JSON_FILE):
    """Permite aproximar e rotular uma única tag."""
    print("\n🏷️  MAPEAMENTO DE TAG INDIVIDUAL")
    print("-" * 60)
    print("Aproxime a tag da antena para identificação.")
    input("Pressione [ENTER] para começar a leitura...")

    epc = capture_single_tag(reader, "Tag Individual")
    if not epc:
        print("❌ Nenhuma tag capturada.")
        return

    db = load_database(json_path)
    prompt_and_save_tag(epc, db, json_path)


def prompt_and_save_tag(epc: str, db: dict, json_path: str):
    """Coleta informações do usuário e persiste a tag no banco JSON."""
    dados_atuais = db.get("tags", {}).get(epc, {})
    nome_padrao = dados_atuais.get("nome", "")
    funcao_padrao = dados_atuais.get("funcao", "geral")
    setup_padrao = dados_atuais.get("setup", "")

    print(f"\n📝 Editando dados para a Tag EPC: {epc}")
    nome = input(f"Nome / Apelido da Tag [{nome_padrao}]: ").strip()
    if not nome:
        nome = nome_padrao or f"Tag {epc[-6:]}"

    print("Função da tag:")
    print("  1: Sensoriamento (inferior / monitoramento de solo/líquido)")
    print("  2: Referência (superior / controle RF)")
    print("  3: Geral / Outro")
    opcao_funcao = input(f"Escolha (1/2/3) [atual: {funcao_padrao}]: ").strip()
    if opcao_funcao == "1":
        funcao = "sensoriamento"
    elif opcao_funcao == "2":
        funcao = "referencia"
    elif opcao_funcao == "3":
        funcao = "geral"
    else:
        funcao = funcao_padrao

    setup = input(f"Experimento / Setup associado [{setup_padrao}]: ").strip()
    if not setup:
        setup = setup_padrao

    db["tags"][epc] = {
        "nome": nome,
        "funcao": funcao,
        "setup": setup,
        "data_cadastro": datetime.now().strftime("%Y-%m-%d")
    }
    save_database(db, json_path)
    print(f"✅ Tag '{nome}' ({epc}) salva com sucesso!")


# ===================================================================================
# Modo 4: Listar Tags Mapeadas Salvas
# ===================================================================================

def list_registered_tags(json_path: str = DEFAULT_JSON_FILE):
    """Exibe todas as tags individuais e os pares de experimento salvos."""
    db = load_database(json_path)
    tags = db.get("tags", {})
    pares = db.get("pares", [])

    print("\n" + "=" * 90)
    print(f"                    BANCO DE TAGS CADASTRADAS ({len(tags)} tags no total)")
    print("=" * 90)

    if not tags:
        print("  (Nenhuma tag cadastrada ainda. Utilize o mapeador para registrar.)")
    else:
        print(f"| {'Código EPC':<26} | {'Função':<14} | {'Nome / Apelido':<24} | {'Setup':<18} |")
        print("+" + "-"*28 + "+" + "-"*16 + "+" + "-"*26 + "+" + "-"*20 + "+")
        for epc, info in tags.items():
            funcao = info.get("funcao", "geral").capitalize()
            nome = info.get("nome", "—")[:24]
            setup = info.get("setup", "—")[:18]
            print(f"| {epc:<26} | {funcao:<14} | {nome:<24} | {setup:<18} |")
        print("+" + "-"*28 + "+" + "-"*16 + "+" + "-"*26 + "+" + "-"*20 + "+")

    print("\n" + "=" * 90)
    print(f"               PARES DE EXPERIMENTO CADASTRADOS ({len(pares)} pares)")
    print("=" * 90)

    if not pares:
        print("  (Nenhum par de experimento cadastrado ainda.)")
    else:
        for idx, par in enumerate(pares, start=1):
            print(f"  {idx}. 🔬 Experimento: {par.get('experimento')}")
            print(f"     👉 Sensoriamento : {par.get('sensoriamento')}")
            print(f"     👉 Referência    : {par.get('referencia')}")
            if par.get("observacoes"):
                print(f"     ℹ️  Observação   : {par.get('observacoes')}")
            print(f"     📅 Cadastro      : {par.get('data_cadastro', 'N/D')}\n")


# ===================================================================================
# Modo 5: Exportar / Sincronizar com 'anotacoes.md'
# ===================================================================================

def export_to_markdown_format(json_path: str = DEFAULT_JSON_FILE):
    """Gera o texto completo formatado para ser usado em 'anotacoes.md' ou nos experimentos."""
    db = load_database(json_path)
    pares = db.get("pares", [])

    print("\n" + "=" * 76)
    print("       EXPORTAÇÃO DE PARES DE TAGS PARA ARQUIVOS MARKDOWN")
    print("=" * 76)

    if not pares:
        print("Nenhum par de experimento registrado no banco de dados.")
        return

    output_lines = []
    for par in pares:
        nome = par.get("experimento")
        s = par.get("sensoriamento")
        r = par.get("referencia")
        output_lines.append(f"# {nome}")
        output_lines.append(f"# sensoriamento - referencia\n")
        output_lines.append(f"{nome}: {s} - {r}\n")

    full_text = "\n".join(output_lines)
    print(full_text)
    print("=" * 76)


# ===================================================================================
# Menu Principal Interativo
# ===================================================================================

def interactive_menu(port: str, baudrate: int, power: float, mock: bool):
    """Exibe o menu interativo no terminal."""
    current_port = port
    current_power = power
    reader = None

    while True:
        print_banner()
        print(f"  Porta Serial: {current_port} | Potência: {current_power:.1f} dBm | Modo: {'SIMULADO' if mock else 'REAL'}")
        print("-" * 76)
        print("  1. 📡 Varredura em Tempo Real (Identificar tags no ambiente e RSSI)")
        print("  2. 🎯 Assistente Guiado: Mapear Par (Sensoriamento + Referência)")
        print("  3. 🏷️  Mapear / Nomear Tag Individual")
        print("  4. 📋 Listar Tags Mapeadas Salvas")
        print("  5. ✍️  Exportar Blocos Formatados para Markdown / anotacoes.md")
        print("  6. ⚙️  Ajustar Configurações (Porta Serial / Potência RF)")
        print("  0. 🚪 Sair")
        print("-" * 76)

        escolha = input("Selecione uma opção (0-6): ").strip()

        if escolha == "1":
            if reader is None:
                reader = init_reader(current_port, baudrate, current_power, mock=mock)
            if reader:
                run_live_scan(reader)

        elif escolha == "2":
            if reader is None:
                reader = init_reader(current_port, baudrate, current_power, mock=mock)
            if reader:
                run_pair_wizard(reader)

        elif escolha == "3":
            if reader is None:
                reader = init_reader(current_port, baudrate, current_power, mock=mock)
            if reader:
                run_single_tag_wizard(reader)

        elif escolha == "4":
            list_registered_tags()
            input("\nPressione [ENTER] para voltar ao menu...")

        elif escolha == "5":
            export_to_markdown_format()
            input("\nPressione [ENTER] para voltar ao menu...")

        elif escolha == "6":
            print("\n⚙️  CONFIGURAÇÕES")
            print(f"Porta atual: {current_port}")
            nova_porta = input(f"Nova porta serial [pressione ENTER para manter '{current_port}']: ").strip()
            if nova_porta:
                current_port = nova_porta
                if reader:
                    reader.close()
                    reader = None

            print(f"Potência RF atual: {current_power:.1f} dBm")
            nova_pot = input(f"Nova potência em dBm (10.0 a 30.0) [ENTER para manter]: ").strip()
            if nova_pot:
                try:
                    val = float(nova_pot)
                    if 10.0 <= val <= 33.0:
                        current_power = val
                        if reader:
                            reader.set_rf_power(current_power)
                    else:
                        print("Valor fora da faixa permitida (10.0 a 33.0 dBm).")
                except ValueError:
                    print("Valor de potência inválido.")

        elif escolha == "0":
            print("\nEncerrando mapeador de tags. Até logo!")
            if reader:
                reader.close()
            break
        else:
            print("Opção inválida, tente novamente.")


# ===================================================================================
# Ponto de Entrada (CLI)
# ===================================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Mapeador de Tags RFID UHF para o Leitor IN-R200 (MagicRF M100)"
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="Inicia diretamente a varredura contínua de tags no ambiente"
    )
    parser.add_argument(
        "--pair", action="store_true",
        help="Inicia diretamente o assistente guiado de mapeamento de par (Sensoriamento + Referência)"
    )
    parser.add_argument(
        "--single", action="store_true",
        help="Inicia diretamente o assistente para mapear uma tag individual"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Exibe as tags cadastradas e encerra"
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Exibe o formato pronto para 'anotacoes.md' e encerra"
    )
    parser.add_argument(
        "--port", default=DEFAULT_SERIAL_PORT,
        help=f"Porta serial do leitor (padrão: {DEFAULT_SERIAL_PORT})"
    )
    parser.add_argument(
        "--baudrate", type=int, default=DEFAULT_BAUDRATE,
        help=f"Baudrate da comunicação serial (padrão: {DEFAULT_BAUDRATE})"
    )
    parser.add_argument(
        "--power", type=float, default=DEFAULT_SCAN_POWER,
        help=f"Potência RF do leitor em dBm (padrão: {DEFAULT_SCAN_POWER})"
    )
    parser.add_argument(
        "--json", default=DEFAULT_JSON_FILE,
        help=f"Arquivo de banco de dados JSON (padrão: {DEFAULT_JSON_FILE})"
    )
    parser.add_argument(
        "--anotacoes", default=DEFAULT_MD_FILE,
        help=f"Arquivo Markdown de anotações (padrão: {DEFAULT_MD_FILE})"
    )
    parser.add_argument(
        "--simulado", action="store_true",
        help="Executa em modo de simulação (sem necessidade de hardware físico conectado)"
    )
    parser.add_argument(
        "--timeout", type=float, default=None,
        help="Tempo em segundos para encerrar a varredura (opcional)"
    )

    args = parser.parse_args()

    # Operações diretas via CLI
    if args.list:
        list_registered_tags(json_path=args.json)
        return

    if args.export:
        export_to_markdown_format(json_path=args.json)
        return

    if args.scan:
        reader = init_reader(args.port, args.baudrate, args.power, mock=args.simulado)
        if reader:
            try:
                run_live_scan(reader, json_path=args.json, duration=args.timeout)
            finally:
                reader.close()
        return

    if args.pair:
        reader = init_reader(args.port, args.baudrate, args.power, mock=args.simulado)
        if reader:
            try:
                run_pair_wizard(reader, json_path=args.json, md_path=args.anotacoes)
            finally:
                reader.close()
        return

    if args.single:
        reader = init_reader(args.port, args.baudrate, args.power, mock=args.simulado)
        if reader:
            try:
                run_single_tag_wizard(reader, json_path=args.json)
            finally:
                reader.close()
        return

    # Se nenhum argumento de ação direta foi passado, abre o menu interativo
    interactive_menu(
        port=args.port,
        baudrate=args.baudrate,
        power=args.power,
        mock=args.simulado
    )


if __name__ == "__main__":
    main()
