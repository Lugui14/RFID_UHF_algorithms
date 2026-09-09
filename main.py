"""
===================================================================================
 Experimento 5: Medições de MRT, DMRT e RSSI - Antena 60 cm Acima do Vaso
===================================================================================
 Descrição:
 - Executa a varredura linear de potência RF (MRT, MRT Filtrado, RSSI e DMRT)
   utilizando as tags de sensoriamento e referência indicadas em
   experimento_5/experimento5.md.
 - Antena posicionada a 60 cm acima do vaso (visada superior vertical).
 - Suporta as etapas do experimento:
     1: Solo Seco (Padrão)
     2: Solo com 30g de Água
     3: Solo com 60g de Água
     4: Solo com 90g de Água
 - Ao encerrar (por término das 200 varreduras ou Ctrl+C), exporta:
     - Gráfico PNG de 3 painéis (MRT, DMRT e RSSI)
     - Planilha CSV de resultados
   diretamente no diretório experimento_5/.
===================================================================================
"""

import os
import re
import sys
import time
import argparse
from typing import Dict, Tuple
from in_r200_driver import INR200Reader
from mrt_calculator import MRTCalculator
from dmrt_exporter import DMRTExporter

# Quantidade padrão de leituras/varreduras
DEFAULT_TARGET_READINGS = 200
TAG_TIMEOUT = 10.0

# Definição das etapas do Experimento 5
ETAPAS = {
    1: {
        "slug": "solo_seco",
        "label": "Solo Seco",
        "title": "Experimento 5 - Solo Seco - Antena 60 cm Acima",
        "csv": "experimento_5/solo_seco_antena_60cm_resultados.csv",
        "chart": "experimento_5/solo_seco_antena_60cm_grafico.png",
    },
    2: {
        "slug": "solo_30g_agua",
        "label": "Solo + 30g Água",
        "title": "Experimento 5 - Solo com 30g de Água - Antena 60 cm Acima",
        "csv": "experimento_5/solo_30g_agua_antena_60cm_resultados.csv",
        "chart": "experimento_5/solo_30g_agua_antena_60cm_grafico.png",
    },
    3: {
        "slug": "solo_60g_agua",
        "label": "Solo + 60g Água",
        "title": "Experimento 5 - Solo com 60g de Água - Antena 60 cm Acima",
        "csv": "experimento_5/solo_60g_agua_antena_60cm_resultados.csv",
        "chart": "experimento_5/solo_60g_agua_antena_60cm_grafico.png",
    },
    4: {
        "slug": "solo_90g_agua",
        "label": "Solo + 90g Água",
        "title": "Experimento 5 - Solo com 90g de Água - Antena 60 cm Acima",
        "csv": "experimento_5/solo_90g_agua_antena_60cm_resultados.csv",
        "chart": "experimento_5/solo_90g_agua_antena_60cm_grafico.png",
    },
}

# Dicionário de tags detectadas durante a execução
scanned_tags: Dict[str, dict] = {}


def load_tags_from_markdown(md_path: str = "experimento_5/experimento5.md") -> Tuple[str, str]:
    """
    Carrega as tags de sensoriamento e referência diretamente do arquivo markdown.
    Usa fallbacks seguros caso o arquivo não seja encontrado ou a regex falhe.
    """
    default_sensing = "E2806995000050136FD09D75"
    default_ref = "E2806995000050136FD0A175"

    if not os.path.exists(md_path):
        return default_sensing, default_ref

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        m_sens = re.search(r"Tag\s+Sensoriamento\s*:\s*([0-9A-Fa-f]+)", content)
        m_ref = re.search(r"Tag\s+de\s+Refer[eê]ncia\s*:\s*([0-9A-Fa-f]+)", content)

        sensing = m_sens.group(1).strip().upper() if m_sens else default_sensing
        reference = m_ref.group(1).strip().upper() if m_ref else default_ref
        return sensing, reference
    except Exception as e:
        print(f"⚠️ Aviso: Não foi possível ler tags de {md_path} ({e}). Usando tags padrão.")
        return default_sensing, default_ref


def is_tag_active(epc: str, current_time: float) -> bool:
    """Retorna True se a tag foi lida nos últimos TAG_TIMEOUT segundos."""
    if epc not in scanned_tags:
        return False
    return (current_time - scanned_tags[epc]["last_seen"]) <= TAG_TIMEOUT


def print_table(reading_counter: int, target_readings: int, setup_label: str, sensing_epc: str, reference_epc: str, current_time: float):
    """
    Imprime a tabela formatada em tempo real com RSSI, Raw MRT, Filtered MRT e DMRT.
    """
    pct = (reading_counter / target_readings) * 100.0
    header = f" EXPERIMENTO 5 - {setup_label.upper()} (ANTENA 60 CM ACIMA) | Varredura {reading_counter:04d}/{target_readings:04d} ({pct:.1f}% concluído)"
    divider = "+" + "-" * 17 + "+" + "-" * 12 + "+" + "-" * 26 + "+" + "-" * 11 + "+" + "-" * 13 + "+" + "-" * 16 + "+" + "-" * 12 + "+"

    print("\n" + "=" * 114)
    print(f"{header:<114}")
    print("=" * 114)
    print(divider)
    print(f"| {'Item / Setup':<15} | {'Função':<10} | {'Código EPC':<24} | {'RSSI':<9} | {'Raw MRT':<11} | {'Filtered MRT':<14} | {'DMRT':<10} |")
    print(divider)

    s_active = is_tag_active(sensing_epc, current_time)
    r_active = is_tag_active(reference_epc, current_time)

    dmrt_str = "N/A"
    if s_active and r_active:
        dmrt_val = MRTCalculator.calculate_dmrt(
            scanned_tags[sensing_epc]["filtered_mrt"],
            scanned_tags[reference_epc]["filtered_mrt"]
        )
        dmrt_str = f"{dmrt_val:+.2f} dB"

    # Linha da Tag de Sensoriamento
    if s_active:
        info = scanned_tags[sensing_epc]
        rssi_str = f"-{info['rssi']} dBm"
        raw_mrt_str = f"{info['raw_mrt']:.1f} dBm"
        filt_mrt_str = f"{info['filtered_mrt']:.2f} dBm"
    else:
        rssi_str = "Not seen"
        raw_mrt_str = "N/A"
        filt_mrt_str = "N/A"

    print(f"| {setup_label:<15} | {'Sensor':<10} | {sensing_epc:<24} | {rssi_str:<9} | {raw_mrt_str:<11} | {filt_mrt_str:<14} | {dmrt_str:<10} |")

    # Linha da Tag de Referência
    if r_active:
        info = scanned_tags[reference_epc]
        rssi_str = f"-{info['rssi']} dBm"
        raw_mrt_str = f"{info['raw_mrt']:.1f} dBm"
        filt_mrt_str = f"{info['filtered_mrt']:.2f} dBm"
    else:
        rssi_str = "Not seen"
        raw_mrt_str = "N/A"
        filt_mrt_str = "N/A"

    print(f"| {'':<15} | {'Referência':<10} | {reference_epc:<24} | {rssi_str:<9} | {raw_mrt_str:<11} | {filt_mrt_str:<14} | {'':<10} |")
    print(divider)

    # Exibe tags extras caso detectadas no ambiente
    other_epcs = [epc for epc in scanned_tags if epc not in (sensing_epc, reference_epc)]
    if other_epcs:
        for idx, epc in enumerate(other_epcs):
            label = "Outras Tags" if idx == 0 else ""
            if is_tag_active(epc, current_time):
                info = scanned_tags[epc]
                rssi_str = f"-{info['rssi']} dBm"
                raw_mrt_str = f"{info['raw_mrt']:.1f} dBm"
                filt_mrt_str = f"{info['filtered_mrt']:.2f} dBm"
            else:
                rssi_str = "Not seen"
                raw_mrt_str = "N/A"
                filt_mrt_str = "N/A"
            print(f"| {label:<15} | {'Extra':<10} | {epc:<24} | {rssi_str:<9} | {raw_mrt_str:<11} | {filt_mrt_str:<14} | {'N/A':<10} |")
        print(divider)


def main():
    parser = argparse.ArgumentParser(description="Experimento 5: Leituras MRT, DMRT e RSSI (Antena 60 cm Acima do Vaso)")
    parser.add_argument("--etapa", type=int, choices=[1, 2, 3, 4], default=1,
                        help="Etapa: 1=Solo Seco (padrão), 2=Solo 30g, 3=Solo 60g, 4=Solo 90g")
    parser.add_argument("--readings", type=int, default=DEFAULT_TARGET_READINGS,
                        help=f"Quantidade de varreduras a realizar (padrão: {DEFAULT_TARGET_READINGS})")
    parser.add_argument("--port", default="/dev/ttyUSB0",
                        help="Porta serial do leitor (padrão: /dev/ttyUSB0)")
    parser.add_argument("--baudrate", type=int, default=115200,
                        help="Baudrate da porta serial (padrão: 115200)")
    parser.add_argument("--md", default="experimento_5/experimento5.md",
                        help="Arquivo markdown com a definição das tags")
    args = parser.parse_args()

    # 1. Carrega tags do markdown
    sensing_epc, reference_epc = load_tags_from_markdown(args.md)

    etapa = ETAPAS[args.etapa]
    target_readings = args.readings
    csv_path = etapa["csv"]
    chart_path = etapa["chart"]
    setup_title = etapa["title"]
    setup_label = etapa["label"]

    print("=" * 114)
    print(f"      IN-R200 UHF RFID Reader - {setup_title}")
    print("=" * 114)
    print(f"📄 Arquivo Markdown  : {args.md}")
    print(f"📌 Tag Sensoriamento : {sensing_epc}")
    print(f"📌 Tag Referência    : {reference_epc}")
    print(f"⚡ Faixa de Potência : 15.0 dBm a 32.0 dBm (Especificação do leitor + Ganho Antena)")
    print(f"🎯 Meta de Leituras : {target_readings} varreduras")
    print(f"📁 Arquivo CSV      : {csv_path}")
    print(f"📈 Gráfico PNG      : {chart_path}")
    print("=" * 114)

    # 2. Conecta ao leitor na porta serial
    reader = INR200Reader(port=args.port, baudrate=args.baudrate)
    if not reader.connect():
        print(f"❌ Não foi possível conectar ao leitor em {args.port}.")
        print(f"👉 Verifique permissões: sudo chmod 666 {args.port}")
        sys.exit(1)

    # 3. Inicializa MRT Calculator (15.0 a 32.0 dBm com passo de 1.0 dBm)
    mrt_calc = MRTCalculator(
        reader=reader,
        min_power=15.0,
        max_power=32.0,
        power_step=1.0,
        dwell_time=0.04
    )

    # 4. Inicializa exportador de dados
    exporter = DMRTExporter()

    print("\n📡 Iniciando varreduras de MRT...")
    print("   (Você pode interromper a qualquer momento com Ctrl+C para gerar os gráficos parciais/finais)\n")

    reading_counter = 0

    try:
        while reading_counter < target_readings:
            reading_counter += 1

            # Executa 1 iteração de varredura de potência
            scan_results = mrt_calc.linear_sweep_details(verbose=False)

            # Atualiza dados das tags
            for epc, info in scan_results.items():
                raw_mrt = info["mrt"]
                filtered_mrt = mrt_calc.apply_low_pass_filter(epc, raw_mrt)
                now = time.time()

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
            s_active = is_tag_active(sensing_epc, current_time)
            r_active = is_tag_active(reference_epc, current_time)

            s_data = scanned_tags.get(sensing_epc) if s_active else None
            r_data = scanned_tags.get(reference_epc) if r_active else None

            dmrt_val = None
            if s_data and r_data:
                dmrt_val = MRTCalculator.calculate_dmrt(
                    s_data["filtered_mrt"],
                    r_data["filtered_mrt"]
                )

            # Grava métricas para exportação
            exporter.record_second_full(
                second=reading_counter,
                sensing_raw_mrt=s_data["raw_mrt"] if s_data else None,
                sensing_filt_mrt=s_data["filtered_mrt"] if s_data else None,
                sensing_rssi=s_data["rssi"] if s_data else None,
                ref_raw_mrt=r_data["raw_mrt"] if r_data else None,
                ref_filt_mrt=r_data["filtered_mrt"] if r_data else None,
                ref_rssi=r_data["rssi"] if r_data else None,
                dmrt=dmrt_val
            )

            # Exibe tabela em tempo real no console
            print_table(reading_counter, target_readings, setup_label, sensing_epc, reference_epc, current_time)

    except KeyboardInterrupt:
        print("\n\n⏹️ Teste interrompido pelo usuário.")
    finally:
        # Restaura potência e fecha conexão
        reader.set_rf_power(26.0)
        reader.close()

        # Garante a criação do diretório do experimento e exporta
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        print(f"\n📊 Gerando gráficos e exportando dados para {csv_path}...")
        exporter.export_experiment_chart(
            chart_filename=chart_path,
            csv_filename=csv_path,
            title_prefix=setup_title
        )

    # Imprime tabela do relatório final
    print("\n" + "=" * 114)
    print(f"             RELATÓRIO FINAL: {setup_title.upper()}")
    print("=" * 114)
    print_table(reading_counter, target_readings, setup_label, sensing_epc, reference_epc, time.time())
    print(f"\n✅ Arquivo CSV salvo em: {os.path.abspath(csv_path)}")
    print(f"✅ Gráfico PNG salvo em: {os.path.abspath(chart_path)}")


if __name__ == "__main__":
    main()
