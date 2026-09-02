"""
===================================================================================
 Experimento 3 - Passo 2: Solo com Adição de 100g de Água (20 cm)
===================================================================================
 Descrição:
 - Medição de MRT, DMRT e RSSI ao longo do tempo (alvo: 260 varreduras / ~15 min reais).
 - Tag Sensoriamento : E2806995000050136FD09D75
 - Tag Referência    : E2806995000050136FD0A175
 - Solo              : Turfa fibrosa + 100g de água adicionada
 - Alcance MRT       : 15.0 dBm a 32.0 dBm (Especificação do leitor + ganho de 6 dBi da antena)
 - Distância da antena: ~20 cm
 - Ao encerrar, exporta o gráfico de 3 painéis (MRT, DMRT, RSSI) e o relatório CSV
   em experimento_3/solo_100g_agua_grafico.png e experimento_3/solo_100g_agua_resultados.csv.
===================================================================================
"""

import os
import sys
import time
from typing import Dict
from in_r200_driver import INR200Reader
from mrt_calculator import MRTCalculator
from dmrt_exporter import DMRTExporter

# Quantidade alvo de leituras/varreduras (260 varreduras equivalem a ~15 minutos reais)
TARGET_READINGS = 260

# Tag configuration for Experimento 3
SENSING_EPC = "E2806995000050136FD09D75"
REFERENCE_EPC = "E2806995000050136FD0A175"
SETUP_LABEL = "Solo 100g Água"

TAG_TIMEOUT = 10.0

# Store unique scanned tags metadata
scanned_tags: Dict[str, dict] = {}


def is_tag_active(epc: str, current_time: float) -> bool:
    """Returns True if the tag was read within the last TAG_TIMEOUT seconds."""
    if epc not in scanned_tags:
        return False
    return (current_time - scanned_tags[epc]["last_seen"]) <= TAG_TIMEOUT


def print_table(reading_counter: int, current_time: float):
    """
    Prints a formatted table displaying real-time MRT, DMRT and RSSI for Experimento 3.
    """
    pct = (reading_counter / TARGET_READINGS) * 100.0
    header = f" EXPERIMENTO 3 - SOLO + 100G ÁGUA (20 CM) | Varredura {reading_counter:04d}/{TARGET_READINGS:04d} ({pct:.1f}% concluído)"
    divider = "+" + "-" * 17 + "+" + "-" * 12 + "+" + "-" * 26 + "+" + "-" * 11 + "+" + "-" * 13 + "+" + "-" * 16 + "+" + "-" * 12 + "+"

    print("\n" + "=" * 114)
    print(f"{header:<114}")
    print("=" * 114)
    print(divider)
    print(f"| {'Item / Setup':<15} | {'Função':<10} | {'Código EPC':<24} | {'RSSI':<9} | {'Raw MRT':<11} | {'Filtered MRT':<14} | {'DMRT':<10} |")
    print(divider)

    s_active = is_tag_active(SENSING_EPC, current_time)
    r_active = is_tag_active(REFERENCE_EPC, current_time)

    dmrt_str = "N/A"
    if s_active and r_active:
        dmrt_val = MRTCalculator.calculate_dmrt(
            scanned_tags[SENSING_EPC]["filtered_mrt"],
            scanned_tags[REFERENCE_EPC]["filtered_mrt"]
        )
        dmrt_str = f"{dmrt_val:+.2f} dB"

    # Sensing Tag Row
    if s_active:
        info = scanned_tags[SENSING_EPC]
        rssi_str = f"-{info['rssi']} dBm"
        raw_mrt_str = f"{info['raw_mrt']:.1f} dBm"
        filt_mrt_str = f"{info['filtered_mrt']:.2f} dBm"
    else:
        rssi_str = "Not seen"
        raw_mrt_str = "N/A"
        filt_mrt_str = "N/A"

    print(f"| {SETUP_LABEL:<15} | {'Sensor':<10} | {SENSING_EPC:<24} | {rssi_str:<9} | {raw_mrt_str:<11} | {filt_mrt_str:<14} | {dmrt_str:<10} |")

    # Reference Tag Row
    if r_active:
        info = scanned_tags[REFERENCE_EPC]
        rssi_str = f"-{info['rssi']} dBm"
        raw_mrt_str = f"{info['raw_mrt']:.1f} dBm"
        filt_mrt_str = f"{info['filtered_mrt']:.2f} dBm"
    else:
        rssi_str = "Not seen"
        raw_mrt_str = "N/A"
        filt_mrt_str = "N/A"

    print(f"| {'':<15} | {'Referência':<10} | {REFERENCE_EPC:<24} | {rssi_str:<9} | {raw_mrt_str:<11} | {filt_mrt_str:<14} | {'':<10} |")
    print(divider)

    # Display extra / unassigned tags if detected
    other_epcs = [epc for epc in scanned_tags if epc not in (SENSING_EPC, REFERENCE_EPC)]
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
    print("=" * 114)
    print("      IN-R200 UHF RFID Reader - Experimento 3 (Solo com 100g de Água - 20 cm)")
    print("=" * 114)
    print(f"📌 Tag Sensoriamento : {SENSING_EPC}")
    print(f"📌 Tag Referência    : {REFERENCE_EPC}")
    print(f"⚡ Faixa de Potência  : 15.0 dBm a 32.0 dBm (Especificação do leitor + Ganho Antena)")
    print(f"🎯 Meta de Leituras  : {TARGET_READINGS} varreduras (aprox. 15 minutos reais de execução)")

    # 1. Connect to reader on USB serial port
    reader = INR200Reader(port="/dev/ttyUSB0", baudrate=115200)
    if not reader.connect():
        print("❌ Não foi possível conectar ao leitor em /dev/ttyUSB0.")
        print("👉 Verifique permissões: sudo chmod 666 /dev/ttyUSB0")
        sys.exit(1)

    # 2. Instantiate MRT Calculator (power range: 15.0 a 32.0 dBm, 1.0 dBm step)
    mrt_calc = MRTCalculator(
        reader=reader,
        min_power=15.0,
        max_power=32.0,
        power_step=1.0,
        dwell_time=0.04
    )

    # 3. Instantiate Data Exporter
    exporter = DMRTExporter()

    print("\n📡 Iniciando varreduras de MRT...")
    print("   (Você pode interromper a qualquer momento com Ctrl+C para gerar os gráficos parciais/finais)\n")

    reading_counter = 0

    try:
        while reading_counter < TARGET_READINGS:
            start_time = time.time()
            reading_counter += 1

            # Run 1 power sweep iteration
            scan_results = mrt_calc.linear_sweep_details(verbose=False)

            # Update tag data
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
            s_active = is_tag_active(SENSING_EPC, current_time)
            r_active = is_tag_active(REFERENCE_EPC, current_time)

            s_data = scanned_tags.get(SENSING_EPC) if s_active else None
            r_data = scanned_tags.get(REFERENCE_EPC) if r_active else None

            dmrt_val = None
            if s_data and r_data:
                dmrt_val = MRTCalculator.calculate_dmrt(
                    s_data["filtered_mrt"],
                    r_data["filtered_mrt"]
                )

            # Record metrics for exporter
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

            # Render real-time console table
            print_table(reading_counter, current_time)

    except KeyboardInterrupt:
        print("\n\n⏹️ Teste interrompido pelo usuário.")
    finally:
        # Restore power and close reader
        reader.set_rf_power(26.0)
        reader.close()

        # Export chart and CSV in experimento_3 directory
        os.makedirs("experimento_3", exist_ok=True)
        chart_path = "experimento_3/solo_100g_agua_grafico.png"
        csv_path = "experimento_3/solo_100g_agua_resultados.csv"
        
        print("\n📊 Gerando gráficos e exportando dados do Solo com 100g de Água...")
        exporter.export_experiment_chart(
            chart_filename=chart_path,
            csv_filename=csv_path,
            title_prefix="Experimento 3 - Solo com 100g de Água (20 cm)"
        )

    # Print final report table
    print("\n" + "=" * 114)
    print("                     RELATÓRIO FINAL: SOLO COM 100G DE ÁGUA")
    print("=" * 114)
    print_table(reading_counter, time.time())
    print(f"\n✅ Arquivo CSV salvo em: {os.path.abspath(csv_path)}")
    print(f"✅ Gráfico PNG salvo em: {os.path.abspath(chart_path)}")


if __name__ == "__main__":
    main()

