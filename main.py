"""
===================================================================================
 Main Application for IN-R200 UHF RFID Reader
===================================================================================
 Description:
 - Initializes the native IN-R200 Python reader driver.
 - Sets RF antenna power level.
 - Listens for incoming EPC tag reads in real time via a callback function.
 - Aggregates tag statistics (Read count, RSSI, Protocol Control, timestamps).
 - Safely handles Ctrl+C shutdown and displays a complete summary report.
===================================================================================
"""

import time
import sys
from in_r200_driver import INR200Reader

# Dictionary to store unique scanned tags:
# Key   : EPC hex string (e.g. "E200470FF3306026244B0112")
# Value : Dict containing metadata (read count, rssi, pc word, first/last seen timestamps)
scanned_tags = {}


def on_tag_scanned(epc: str, rssi: int, pc: str):
    """
    Callback function invoked by the reader background thread whenever a tag is read.
    
    Parameters:
    - epc  : 96-bit Electronic Product Code string (Unique tag ID)
    - rssi : Received Signal Strength Indicator value (-dBm)
    - pc   : Protocol Control bits (Gen2 header info, e.g. "3400")
    """
    now = time.time()
    
    # Check if this is a newly discovered tag
    if epc not in scanned_tags:
        scanned_tags[epc] = {
            "count": 1,
            "rssi": rssi,
            "pc": pc,
            "first_seen": now,
            "last_seen": now
        }
        print(f" ✨ [NEW TAG DISCOVERED] EPC: {epc} | PC: {pc} | Initial RSSI: -{rssi} dBm")
    else:
        # Tag previously seen: update read counter, RSSI, and timestamp
        scanned_tags[epc]["count"] += 1
        scanned_tags[epc]["rssi"] = rssi
        scanned_tags[epc]["last_seen"] = now
        
        # Display updated live counter on same line (\r)
        print(f" 🏷️  [TAG READ] EPC: {epc} (Reads: {scanned_tags[epc]['count']}) | RSSI: -{rssi} dBm", end="\r")


def main():
    print("=" * 65)
    print("      IN-R200 (MagicRF M100) UHF RFID Reader - Native Linux")
    print("=" * 65)

    # 1. Instantiate reader driver targeting Linux USB serial port at 115200 baud
    reader = INR200Reader(port="/dev/ttyUSB0", baudrate=115200)
    
    # 2. Open serial connection and verify communication
    if not reader.connect():
        print("❌ Could not connect to reader on /dev/ttyUSB0.")
        print("👉 Ensure /dev/ttyUSB0 permissions are granted: sudo chmod 666 /dev/ttyUSB0")
        sys.exit(1)
        
    # 3. Configure RF output power to 26.0 dBm
    reader.set_rf_power(26.0)
    
    print("\n📡 RFID Reader active. Start scanning tags! (Press Ctrl+C to exit)\n")
    
    # 4. Start background inventory scanning thread passing the callback function
    reader.start_inventory(on_tag_scanned)

    # 5. Keep main application thread alive until user presses Ctrl+C
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nStopping RFID inventory scan...")
        
        # 6. Stop inventory loop and close serial port safely
        reader.stop_inventory()
        reader.close()
        
    # 7. Print final summary report of all scanned tags
    print("\n" + "=" * 65)
    print("                     SCAN SUMMARY REPORT")
    print("=" * 65)
    print(f"Total Unique Tags Read: {len(scanned_tags)}\n")
    
    for idx, (epc, info) in enumerate(scanned_tags.items(), 1):
        print(f" {idx}. EPC: {epc}")
        print(f"    - Read Count: {info['count']} times")
        print(f"    - Protocol Control (PC): {info['pc']}")
        print(f"    - Signal Strength (RSSI): -{info['rssi']} dBm")
    print("=" * 65)


if __name__ == "__main__":
    main()
