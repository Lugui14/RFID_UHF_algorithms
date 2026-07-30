"""
===================================================================================
 Minimum Response Threshold (MRT) & Differential MRT (DMRT) Calculator
 Based on GreenTag paper (ACM TOSN 2025 / 3715128.pdf) & IN-R200 Reader Driver
===================================================================================
"""

import time
import sys
from typing import Dict, Optional
from in_r200_driver import INR200Reader


class MRTCalculator:
    """
    Class to calculate MRT and DMRT metrics using the IN-R200 RFID reader driver.
    """
    
    def __init__(
        self,
        reader: INR200Reader,
        min_power: float = 10.0,
        max_power: float = 26.0,
        power_step: float = 0.5,
        dwell_time: float = 0.4
    ):
        """
        Parameters:
        - reader     : Connected INR200Reader instance
        - min_power  : Minimum RF transmit power level in dBm to test
        - max_power  : Maximum RF transmit power level in dBm to test
        - power_step : Resolution step size in dBm (e.g. 0.5 dBm)
        - dwell_time : Duration in seconds to scan at each power level
        """
        self.reader = reader
        self.min_power = min_power
        self.max_power = max_power
        self.power_step = power_step
        self.dwell_time = dwell_time
        
        # Store filtered MRT values for low-pass filtering
        self.filtered_mrt: Dict[str, float] = {}

    def test_tag_read(self, power_dbm: float, target_epc: Optional[str] = None) -> Dict[str, dict]:
        """
        Sets reader power to power_dbm, scans for dwell_time seconds, and returns detected tags.
        """
        detected = {}

        def _cb(epc: str, rssi: int, pc: str):
            epc_clean = epc.upper()
            if target_epc is None or epc_clean == target_epc.upper():
                if epc_clean not in detected:
                    detected[epc_clean] = {"rssi": rssi, "pc": pc, "count": 1}
                else:
                    detected[epc_clean]["count"] += 1

        self.reader.set_rf_power(power_dbm)
        self.reader.start_inventory(_cb)
        time.sleep(self.dwell_time)
        self.reader.stop_inventory()
        return detected

    def linear_sweep_mrt(self) -> Dict[str, float]:
        """
        Sweeps reader transmit power from min_power to max_power.
        Returns a dict mapping EPC -> MRT (dBm) for all detected tags.
        """
        mrt_results: Dict[str, float] = {}
        curr_power = self.min_power
        print(f"\n🔍 Starting Linear Power Sweep ({self.min_power} dBm to {self.max_power} dBm, step {self.power_step} dBm)...")

        while curr_power <= self.max_power:
            detected = self.test_tag_read(curr_power)
            for epc in detected:
                if epc not in mrt_results:
                    mrt_results[epc] = curr_power
                    print(f"  🎯 [MRT FOUND] EPC: {epc} -> MRT = {curr_power:.1f} dBm")

            curr_power = round(curr_power + self.power_step, 2)

        return mrt_results

    def binary_search_mrt(self, target_epc: str) -> Optional[float]:
        """
        Fast Binary Search MRT algorithm (Algorithm 1 from GreenTag paper).
        Finds MRT for a specific target EPC in O(log N) steps.
        """
        target_epc = target_epc.upper()
        low = self.min_power
        high = self.max_power
        step = self.power_step

        print(f"\n⚡ Starting Fast Binary MRT Search for Target Tag: {target_epc}")

        # Step 1: Check maximum power first to confirm target reachability
        if target_epc not in self.test_tag_read(high, target_epc):
            print(f"❌ Target tag {target_epc} is NOT reachable even at maximum power ({high} dBm).")
            return None

        # Step 2: Binary Search
        while low <= high:
            # Round mid power to nearest step grid
            mid = round(((low + high) / 2.0) / step) * step
            mid = round(mid, 2)

            if mid < low or mid > high:
                break

            can_read_mid = target_epc in self.test_tag_read(mid, target_epc)

            if can_read_mid:
                # Check if tag becomes unreadable at (mid - step)
                prev_power = round(mid - step, 2)
                if prev_power < self.min_power or target_epc not in self.test_tag_read(prev_power, target_epc):
                    print(f"  🎯 [BINARY MRT FOUND] EPC: {target_epc} -> MRT = {mid:.1f} dBm")
                    return mid
                else:
                    high = prev_power
            else:
                low = round(mid + step, 2)

        print(f"  ⚠️ Could not determine exact MRT for {target_epc}.")
        return None

    def apply_low_pass_filter(self, epc: str, raw_mrt: float, alpha: float = 0.2) -> float:
        """
        Applies Exponential Moving Average low-pass filter (Eq. 11 in GreenTag paper):
        y_i = alpha * x_i + (1 - alpha) * y_{i-1}
        """
        if epc not in self.filtered_mrt:
            self.filtered_mrt[epc] = raw_mrt
        else:
            self.filtered_mrt[epc] = alpha * raw_mrt + (1.0 - alpha) * self.filtered_mrt[epc]
        return self.filtered_mrt[epc]

    @staticmethod
    def calculate_dmrt(sensing_mrt: float, reference_mrt: float) -> float:
        """
        Calculates Differential Minimum Response Threshold (DMRT):
        DMRT = MRT_sensing (bottom tag) - MRT_reference (top tag)
        """
        return sensing_mrt - reference_mrt


def main():
    print("=" * 65)
    print("  IN-R200 Minimum Response Threshold (MRT) & DMRT Measurement")
    print("=" * 65)

    # 1. Connect to IN-R200 reader
    reader = INR200Reader(port="/dev/ttyUSB0", baudrate=115200)
    if not reader.connect():
        print("❌ Could not connect to reader on /dev/ttyUSB0.")
        sys.exit(1)

    # 2. Instantiate MRT Calculator (power range: 10.0 dBm to 26.0 dBm, 0.5 dBm step)
    mrt_calc = MRTCalculator(
        reader=reader,
        min_power=10.0,
        max_power=26.0,
        power_step=0.5,
        dwell_time=0.4
    )

    try:
        # Option A: Sweep all tags in environment
        all_mrts = mrt_calc.linear_sweep_mrt()

        print("\n" + "=" * 65)
        print("                   MRT SCAN RESULTS")
        print("=" * 65)
        for epc, mrt_val in all_mrts.items():
            filtered = mrt_calc.apply_low_pass_filter(epc, mrt_val)
            print(f" 🏷️  EPC: {epc} | Raw MRT: {mrt_val:.1f} dBm | Filtered MRT: {filtered:.2f} dBm")
        print("=" * 65)

        # Option B: Calculate DMRT if two tags are configured (Bottom Sensing & Top Reference)
        if len(all_mrts) >= 2:
            epc_list = list(all_mrts.keys())
            sensing_epc = epc_list[0]
            reference_epc = epc_list[1]
            
            sensing_mrt = mrt_calc.apply_low_pass_filter(sensing_epc, all_mrts[sensing_epc])
            reference_mrt = mrt_calc.apply_low_pass_filter(reference_epc, all_mrts[reference_epc])
            dmrt = mrt_calc.calculate_dmrt(sensing_mrt, reference_mrt)

            print("\n📊 Differential MRT (DMRT) Calculation:")
            print(f"   - Sensing Tag  (Bottom) EPC: {sensing_epc} | Filtered MRT: {sensing_mrt:.2f} dBm")
            print(f"   - Reference Tag (Top)   EPC: {reference_epc} | Filtered MRT: {reference_mrt:.2f} dBm")
            print(f"   👉 Calculated DMRT: {dmrt:.2f} dB")

    finally:
        # Restore reader power to default 26 dBm and close connection
        reader.set_rf_power(26.0)
        reader.close()


if __name__ == "__main__":
    main()
