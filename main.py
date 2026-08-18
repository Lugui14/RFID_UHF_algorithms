"""
===================================================================================
 Main Application for IN-R200 UHF RFID Reader
===================================================================================
 Description:
 - Initializes native IN-R200 Python reader driver.
 - Integrates MRTCalculator to perform periodic MRT scanning every second.
 - Dynamically loads cup configurations from anotacoes.md (format: copo_name: sensing_epc - reference_epc).
 - Implements 5-second inactivity timeout (marks tags as 'Not seen' after 5s without reads).
 - Calculates DMRT (MRT_sensing - MRT_reference) for each active cup in real time.
 - Displays all tags and DMRT calculations in a structured tabular format.
 - Automatically exports a graphical DMRT chart (PNG) upon stopping detection.
===================================================================================
"""

import os
import time
import sys
from in_r200_driver import INR200Reader
from mrt_calculator import MRTCalculator
from dmrt_exporter import DMRTExporter


def load_cups_config(filepath: str = "anotacoes.md") -> dict:
    """
    Parses cup tag configurations dynamically from an annotations text/markdown file.
    Format expected per line:
        copo <nome>: <epc_sensoriamento> - <epc_referencia>
    """
    cups = {}
    if not os.path.exists(filepath):
        return cups

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line_clean = line.strip()
                if not line_clean or line_clean.startswith("#"):
                    continue
                if ":" in line_clean and "-" in line_clean:
                    parts = line_clean.split(":", 1)
                    cup_name = parts[0].strip().title()
                    epcs = parts[1].split("-", 1)
                    if len(epcs) == 2:
                        sensing = epcs[0].strip().upper()
                        reference = epcs[1].strip().upper()
                        cups[cup_name] = {
                            "sensing": sensing,
                            "reference": reference
                        }
    except Exception as e:
        print(f"⚠️ Error reading annotations file '{filepath}': {e}")

    return cups


# Timeout threshold in seconds (consider tag inactive/'Not seen' after 5.0 seconds)
TAG_TIMEOUT = 5.0

# Dictionary to store unique scanned tags:
# Key   : EPC hex string
# Value : Dict containing metadata (read count, rssi, pc, raw_mrt, filtered_mrt, first/last seen)
scanned_tags = {}


def is_tag_active(epc: str, current_time: float) -> bool:
    """
    Returns True if the tag was read within the last TAG_TIMEOUT seconds, False otherwise.
    """
    if epc not in scanned_tags:
        return False
    return (current_time - scanned_tags[epc]["last_seen"]) <= TAG_TIMEOUT


def print_table(second_counter: int, current_time: float, cups_config: dict):
    """
    Prints a formatted table displaying tags grouped by cup and calculates real-time DMRT.
    Tags not read for > 5 seconds are displayed as 'Not seen' and stop contributing to DMRT.
    """
    header_title = f" SECOND {second_counter:04d} | Real-Time Periodic MRT & DMRT Monitor"
    divider = "+" + "-" * 17 + "+" + "-" * 12 + "+" + "-" * 26 + "+" + "-" * 11 + "+" + "-" * 13 + "+" + "-" * 16 + "+" + "-" * 12 + "+"
    
    print("\n" + "=" * 114)
    print(f"{header_title:<114}")
    print("=" * 114)
    print(divider)
    print(f"| {'Cup / Group':<15} | {'Role':<10} | {'EPC Code':<24} | {'RSSI':<9} | {'Raw MRT':<11} | {'Filtered MRT':<14} | {'DMRT':<10} |")
    print(divider)

    assigned_epcs = set()

    # Render configured cups from anotacoes.md
    for cup_name, tags in cups_config.items():
        sensing_epc = tags["sensing"].upper()
        reference_epc = tags["reference"].upper()
        assigned_epcs.add(sensing_epc)
        assigned_epcs.add(reference_epc)

        s_active = is_tag_active(sensing_epc, current_time)
        r_active = is_tag_active(reference_epc, current_time)

        # Calculate DMRT for this cup ONLY if BOTH sensing and reference tags were read within the last 5s
        dmrt_str = "N/A"
        if s_active and r_active:
            dmrt_val = MRTCalculator.calculate_dmrt(
                scanned_tags[sensing_epc]["filtered_mrt"],
                scanned_tags[reference_epc]["filtered_mrt"]
            )
            dmrt_str = f"{dmrt_val:+.2f} dB"

        # Sensing Tag Row
        if s_active:
            info = scanned_tags[sensing_epc]
            rssi_str = f"-{info['rssi']} dBm"
            raw_mrt_str = f"{info['raw_mrt']:.1f} dBm"
            filt_mrt_str = f"{info['filtered_mrt']:.2f} dBm"
        else:
            rssi_str = "Not seen"
            raw_mrt_str = "N/A"
            filt_mrt_str = "N/A"

        print(f"| {cup_name:<15} | {'Sensor':<10} | {sensing_epc:<24} | {rssi_str:<9} | {raw_mrt_str:<11} | {filt_mrt_str:<14} | {dmrt_str:<10} |")

        # Reference Tag Row
        if r_active:
            info = scanned_tags[reference_epc]
            rssi_str = f"-{info['rssi']} dBm"
            raw_mrt_str = f"{info['raw_mrt']:.1f} dBm"
            filt_mrt_str = f"{info['filtered_mrt']:.2f} dBm"
        else:
            rssi_str = "Not seen"
            raw_mrt_str = "N/A"
            filt_mrt_str = "N/A"

        print(f"| {'':<15} | {'Reference':<10} | {reference_epc:<24} | {rssi_str:<9} | {raw_mrt_str:<11} | {filt_mrt_str:<14} | {'':<10} |")
        print(divider)

    # Print unassigned / extra tags detected in the environment
    other_epcs = [epc for epc in scanned_tags if epc.upper() not in assigned_epcs]
    if other_epcs:
        for idx, epc in enumerate(other_epcs):
            group_label = "Unassigned" if idx == 0 and not cups_config else ("Other Tags" if idx == 0 else "")
            if is_tag_active(epc, current_time):
                info = scanned_tags[epc]
                rssi_str = f"-{info['rssi']} dBm"
                raw_mrt_str = f"{info['raw_mrt']:.1f} dBm"
                filt_mrt_str = f"{info['filtered_mrt']:.2f} dBm"
            else:
                rssi_str = "Not seen"
                raw_mrt_str = "N/A"
                filt_mrt_str = "N/A"
            print(f"| {group_label:<15} | {'General':<10} | {epc:<24} | {rssi_str:<9} | {raw_mrt_str:<11} | {filt_mrt_str:<14} | {'N/A':<10} |")
        print(divider)


def main():
    print("=" * 114)
    print("      IN-R200 UHF RFID Reader - Dynamic Periodic Real-Time MRT & DMRT Monitor")
    print("=" * 114)

    # Load cup configuration dynamically from anotacoes.md
    cups_config = load_cups_config("anotacoes.md")
    if cups_config:
        print(f"📋 Loaded {len(cups_config)} cup configuration(s) from anotacoes.md:")
        for cup, cfg in cups_config.items():
            print(f"   - {cup}: Sensor={cfg['sensing']} | Reference={cfg['reference']}")
    else:
        print("ℹ️ No cup configuration found in anotacoes.md. Monitoring all detected tags in general mode.")

    # 1. Instantiate reader driver targeting Linux USB serial port at 115200 baud
    reader = INR200Reader(port="/dev/ttyUSB0", baudrate=115200)
    
    # 2. Open serial connection and verify communication
    if not reader.connect():
        print("❌ Could not connect to reader on /dev/ttyUSB0.")
        print("👉 Ensure /dev/ttyUSB0 permissions are granted: sudo chmod 666 /dev/ttyUSB0")
        sys.exit(1)
        
    # 3. Instantiate MRT Calculator
    mrt_calc = MRTCalculator(
        reader=reader,
        min_power=10.0,
        max_power=26.0,
        power_step=1.0,
        dwell_time=0.04
    )

    # 4. Instantiate DMRT Exporter for logging and graphic generation
    exporter = DMRTExporter()
    
    print("\n📡 Periodic MRT Scanner active. Displaying DMRT results every second...")
    print("   (Press Ctrl+C to stop scanning and view final summary/graphic chart)\n")
    
    second_counter = 0

    try:
        while True:
            start_time = time.time()
            second_counter += 1

            # Execute MRT power sweep for current 1-second window
            scan_results = mrt_calc.linear_sweep_details(verbose=False)

            # Process and aggregate detected tag data
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

            # Collect DMRT readings for exporter for this second
            current_time = time.time()
            dmrt_by_cup = {}
            for cup_name, tags in cups_config.items():
                s_epc = tags["sensing"].upper()
                r_epc = tags["reference"].upper()
                if is_tag_active(s_epc, current_time) and is_tag_active(r_epc, current_time):
                    dmrt_by_cup[cup_name] = MRTCalculator.calculate_dmrt(
                        scanned_tags[s_epc]["filtered_mrt"],
                        scanned_tags[r_epc]["filtered_mrt"]
                    )
                else:
                    dmrt_by_cup[cup_name] = None

            exporter.record_second(second_counter, dmrt_by_cup)

            # Print tabular format with DMRT for each second
            print_table(second_counter, current_time, cups_config)

            # Sleep remaining time of the 1-second interval
            elapsed = time.time() - start_time
            time.sleep(max(0.0, 1.0 - elapsed))

    except KeyboardInterrupt:
        print("\n\nStopping periodic MRT inventory scan...")
    finally:
        # Restore reader RF power to default 26.0 dBm and close serial port
        reader.set_rf_power(26.0)
        reader.close()
        # Export graphic chart and CSV report at end of detection
        exporter.export_chart("dmrt_results.png", "dmrt_results.csv")

    # Print final summary table
    print("\n" + "=" * 114)
    print("                     FINAL PERIODIC MRT & DMRT REPORT")
    print("=" * 114)
    print_table(second_counter, time.time(), cups_config)


if __name__ == "__main__":
    main()
