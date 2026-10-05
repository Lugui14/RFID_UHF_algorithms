"""
===================================================================================
 IN-R200 / MagicRF M100 UHF RFID Reader Native Linux Driver
===================================================================================
 Protocol Specifications (Discovered from SDK RFID_Reader_Cmds.dll):
 
 Frame Structure:
 [HEADER] [TYPE] [COMMAND] [LEN_MSB] [LEN_LSB] [DATA_PAYLOAD] [CHECKSUM] [ENDER]
   1 Byte  1 Byte   1 Byte    1 Byte    1 Byte    N Bytes      1 Byte   1 Byte
 
 - HEADER   : Always 0xAA (Marks the beginning of a serial packet)
 - TYPE     : 0x00 = Host Command, 0x01 = Reader Response, 0x02 = Info/Tag Report
 - COMMAND  : 0x03 = Get Hardware Info, 0xB6 = Set Power, 0x27 = Read Multi Tag, 0x28 = Stop Read
 - LENGTH   : 2 Bytes representing length of DATA_PAYLOAD in bytes (Big Endian)
 - DATA     : Command-specific payload
 - CHECKSUM : LSB of the sum of all bytes in (TYPE + COMMAND + LENGTH + DATA) mod 256
 - ENDER    : Always 0xDD (Marks the end of a serial packet)
===================================================================================
"""

import time
import threading
import serial
from typing import Callable, Optional, Tuple, Dict


def calc_checksum(hex_str: str) -> str:
    """
    Calculates the 8-bit checksum for the M100 protocol frame.
    
    Algorithm:
    1. Converts hex string payload into byte array.
    2. Sums all byte values.
    3. Performs bitwise AND with 0xFF (mod 256) to extract the LSB (Least Significant Byte).
    4. Returns checksum as a 2-character uppercase hex string (e.g. "4D").
    """
    clean_hex = hex_str.replace(" ", "")
    byte_vals = [int(clean_hex[i:i+2], 16) for i in range(0, len(clean_hex), 2)]
    chk = sum(byte_vals) & 0xFF
    return f"{chk:02X}"


def build_frame(msg_type: str, cmd_code: str, data: str = "") -> bytes:
    """
    Constructs a complete binary serial packet according to the AA...DD protocol.
    
    Parameters:
    - msg_type : Hex string for message type ("00" for command from host)
    - cmd_code : Hex string for command code (e.g., "03" for info, "27" for read)
    - data     : Optional hex string payload
    
    Returns:
    - bytes object ready to be sent over serial port.
    """
    clean_data = data.replace(" ", "")
    data_len_bytes = len(clean_data) // 2
    
    # Format length as 4 hex characters (2 bytes, Big Endian)
    len_str = f"{data_len_bytes:04X}"
    
    # Assemble payload without header and ender to calculate checksum
    payload_str = msg_type + cmd_code + len_str + clean_data
    checksum_str = calc_checksum(payload_str)
    
    # Complete frame: AA + payload + checksum + DD
    frame_hex = "AA" + payload_str + checksum_str + "DD"
    return bytes.fromhex(frame_hex)


class INR200Reader:
    """
    Python driver for the IN-R200 UHF RFID reader module (MagicRF M100 chip).
    Manages serial connection, configuration, tag inventory scanning, and data parsing.
    """
    
    HARDWARE_MIN_POWER = 15.0  # Limite físico inferior do chip MagicRF M100
    HARDWARE_MAX_POWER = 26.0  # Limite físico superior do chip MagicRF M100

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        """
        Initialize reader instance with port and baud rate.
        Default port: /dev/ttyUSB0 (CP210x / CH340 USB-Serial interface)
        Default baudrate: 115200 bps
        """
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None
        self.is_reading = False
        self._read_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """
        Opens serial port, asserts DTR/RTS lines for USB power, and tests communication.
        Returns True if successful, False otherwise.
        """
        try:
            # Open PySerial port with 0.2s timeout
            self.ser = serial.Serial(self.port, baudrate=self.baudrate, timeout=0.2)
            
            # Assert DTR and RTS control lines (required to power/enable USB serial chips)
            self.ser.dtr = True
            self.ser.rts = True
            
            # Flush any old unread garbage from input buffer
            self.ser.reset_input_buffer()
            time.sleep(0.1)
            
            # Query reader module version to confirm active communication
            info = self.get_module_info()
            print(f"✅ Connected to IN-R200 Reader on {self.port} ({info})")
            return True
        except serial.SerialException as e:
            print(f"❌ Failed to connect on {self.port}: {e}")
            return False

    def get_module_info(self) -> str:
        """
        Queries hardware/firmware string from reader (Cmd 0x03).
        Returns reader model string (e.g. 'M100 26dBm V1.0').
        """
        with self._lock:
            if not self.ser or not self.ser.is_open:
                return "Not Connected"
                
            pkt = build_frame("00", "03", "00")
            self.ser.reset_input_buffer()
            self.ser.write(pkt)
            self.ser.flush()
            time.sleep(0.05)
            
            # Read response packet
            t0 = time.time()
            buf = bytearray()
            while time.time() - t0 < 0.2:
                if self.ser.in_waiting > 0:
                    buf.extend(self.ser.read(self.ser.in_waiting))
                    if len(buf) >= 7 and buf[0] == 0xAA:
                        data_len = (buf[3] << 8) | buf[4]
                        if len(buf) >= 7 + data_len and buf[6 + data_len] == 0xDD:
                            payload = buf[5:5+data_len]
                            return payload[2:].decode('ascii', errors='ignore').strip()
                time.sleep(0.01)
            return "IN-R200 UHF Reader"

    def set_rf_power(self, power_dbm: float = 26.0, delay: float = 0.02) -> bool:
        """
        Configures reader RF Output Power in dBm (e.g., 26.0 dBm).
        Clamps to hardware limits [15.0, 26.0] dBm.
        Flushes buffers before and after to ensure no residual frames leak.
        """
        with self._lock:
            if not self.ser or not self.ser.is_open:
                return False
                
            clamped_power = max(self.HARDWARE_MIN_POWER, min(self.HARDWARE_MAX_POWER, round(power_dbm, 1)))
            power_val = int(clamped_power * 100)
            data_hex = f"{power_val:04X}"
            pkt = build_frame("00", "B6", data_hex)
            
            # Limpa qualquer resíduo na serial antes de enviar nova potência
            self.ser.reset_input_buffer()
            self.ser.write(pkt)
            self.ser.flush()

            # Aguarda e drena a resposta de confirmação (Cmd 0xB6)
            t0 = time.time()
            confirmed = False
            while time.time() - t0 < 0.1:
                if self.ser.in_waiting > 0:
                    resp = self.ser.read(self.ser.in_waiting)
                    if 0xB6 in resp:
                        confirmed = True
                        break
                time.sleep(0.005)

            if delay > 0:
                time.sleep(delay)

            # Limpa qualquer eco ou lixo residual
            if self.ser.in_waiting > 0:
                self.ser.reset_input_buffer()

            return confirmed

    def get_rf_power(self) -> float:
        """
        Queries the current PA output power directly from the reader (Cmd 0xB7).
        """
        with self._lock:
            if not self.ser or not self.ser.is_open:
                return 26.0
            pkt = build_frame("00", "B7")
            self.ser.reset_input_buffer()
            self.ser.write(pkt)
            self.ser.flush()
            t0 = time.time()
            buf = bytearray()
            while time.time() - t0 < 0.15:
                if self.ser.in_waiting > 0:
                    buf.extend(self.ser.read(self.ser.in_waiting))
                    if len(buf) >= 8 and buf[0] == 0xAA:
                        dlen = (buf[3] << 8) | buf[4]
                        if len(buf) >= 7 + dlen and buf[6 + dlen] == 0xDD:
                            p_val = int.from_bytes(buf[5:5+dlen], byteorder='big')
                            return p_val / 100.0
                time.sleep(0.005)
            return 26.0

    def read_multi_tag(
        self,
        loop_count: int = 3,
        timeout: float = 0.15,
        target_epc: Optional[str] = None
    ) -> Dict[str, dict]:
        """
        Executes a bounded burst of multi-tag inventory rounds using Cmd 0x27 (Read Multi Tag)
        with continuous RF carrier wave (CW) across loop_count rounds.
        
        Parameters:
        - loop_count : Number of inventory rounds to execute (default: 3 rounds).
                       Keeps the RF carrier active, giving passive tags sufficient energy
                       to power on and respond at threshold RF power levels.
        - timeout    : Maximum time in seconds to wait for responses (default: 0.15s).
        - target_epc : Optional target EPC string. If provided, stops as soon as the target
                       is detected, draining any residual bytes to keep buffers clean.
                       
        Returns:
        - Dict[str, dict]: Mapping EPC -> {'rssi': int, 'pc': str, 'count': int}.
        Synchronous, thread-safe, self-terminating, and leaves the serial buffer completely empty.
        """
        clean_target = target_epc.upper() if target_epc else None
        clamped_loops = max(1, min(65535, loop_count))
        pkt = build_frame("00", "27", f"22{clamped_loops:04X}")

        with self._lock:
            if not self.ser or not self.ser.is_open:
                return {}

            self.ser.reset_input_buffer()
            self.ser.write(pkt)
            self.ser.flush()

            t0 = time.time()
            buf = bytearray()
            results: Dict[str, dict] = {}

            while time.time() - t0 < timeout:
                if self.ser.in_waiting > 0:
                    buf.extend(self.ser.read(self.ser.in_waiting))
                    
                    while len(buf) >= 7:
                        aa_pos = buf.find(0xAA)
                        if aa_pos == -1:
                            buf.clear()
                            break
                        if aa_pos > 0:
                            buf = buf[aa_pos:]
                            
                        if len(buf) < 7:
                            break
                            
                        dlen = (buf[3] << 8) | buf[4]
                        total_len = 7 + dlen
                        if len(buf) >= total_len:
                            pkt_bytes = bytes(buf[:total_len])
                            buf = buf[total_len:]
                            
                            if pkt_bytes[-1] == 0xDD:
                                cmd = pkt_bytes[2]
                                if cmd == 0x22 and dlen >= 5:
                                    payload = pkt_bytes[5:5+dlen]
                                    rssi = int.from_bytes(payload[0:1], byteorder="big", signed=True)
                                    pc = payload[1:3].hex().upper()
                                    epc = payload[3:-2].hex().upper() if dlen > 5 else payload[3:].hex().upper()
                                    
                                    if clean_target is None or epc == clean_target:
                                        if epc not in results:
                                            results[epc] = {"rssi": rssi, "pc": pc, "count": 1}
                                        else:
                                            results[epc]["count"] += 1
                                            results[epc]["rssi"] = rssi
                        else:
                            break

                if clean_target and clean_target in results:
                    break

                if len(results) > 0 and sum(r["count"] for r in results.values()) >= clamped_loops:
                    break

                time.sleep(0.002)

            time.sleep(0.005)
            if self.ser.in_waiting > 0:
                self.ser.reset_input_buffer()

            return results

    def read_single_tag(self, timeout: float = 0.15) -> Optional[Tuple[str, int, str]]:
        """
        Executes a single synchronous tag interrogation round using Cmd 0x22 (Read Single Tag).
        Returns (epc, rssi_dbm, pc) if a tag responds, or None if no tag / timeout.
        Thread-safe, synchronous, and guaranteed NOT to leave background streaming in the buffer.
        """
        res = self.read_multi_tag(loop_count=1, timeout=timeout)
        if res:
            first_epc = next(iter(res))
            info = res[first_epc]
            return first_epc, info["rssi"], info["pc"]
        return None

    def start_inventory(self, tag_callback: Callable[[str, int, str], None]):
        """
        Launches background thread to continuously scan for RFID tags.
        
        Parameters:
        - tag_callback: Function called when a tag is read -> callback(epc: str, rssi: int, pc: str)
        """
        if self.is_reading:
            return
        self.is_reading = True
        
        # Cmd 0x27 = Read Multi Tag, Payload = "22FFFF" (repetir Cmd 0x22 por 65535 rounds)
        pkt_start = build_frame("00", "27", "22FFFF")

        def _reader_loop():
            """
            Background worker thread function with Watchdog mechanism.
            Continuously reads incoming serial bytes and parses AA...DD frames.
            """
            buffer = bytearray()
            last_cmd_sent = 0
            
            while self.is_reading:
                now = time.time()
                
                # Re-dispara inventário a cada 1.0s se nenhum dado novo chegar
                if now - last_cmd_sent > 1.0:
                    with self._lock:
                        if self.ser and self.ser.is_open:
                            self.ser.write(pkt_start)
                            self.ser.flush()
                            last_cmd_sent = now

                # Leitura segura com lock
                chunk = b""
                with self._lock:
                    if self.ser and self.ser.is_open and self.ser.in_waiting > 0:
                        chunk = self.ser.read(self.ser.in_waiting)

                if chunk:
                    buffer.extend(chunk)
                    
                    # Parseamento estrito de frames usando data_len e delimitadores
                    while len(buffer) >= 7:
                        aa_pos = buffer.find(0xAA)
                        if aa_pos == -1:
                            buffer.clear()
                            break
                        if aa_pos > 0:
                            buffer = buffer[aa_pos:]
                            
                        if len(buffer) < 7:
                            break
                            
                        data_len = (buffer[3] << 8) | buffer[4]
                        total_len = 7 + data_len
                        if len(buffer) >= total_len:
                            pkt = bytes(buffer[:total_len])
                            buffer = buffer[total_len:]
                            
                            if pkt[-1] == 0xDD and pkt[2] in (0x22, 0x27):
                                payload = pkt[5:5+data_len]
                                if len(payload) >= 5:
                                    last_cmd_sent = time.time()
                                    # RSSI com sinal em complemento de dois
                                    rssi = int.from_bytes(payload[0:1], byteorder="big", signed=True)
                                    pc = payload[1:3].hex().upper()
                                    epc = payload[3:-2].hex().upper() if len(payload) > 5 else payload[3:].hex().upper()
                                    if epc:
                                        tag_callback(epc, rssi, pc)
                        else:
                            break
                time.sleep(0.01)

        # Dispara thread daemon
        self._read_thread = threading.Thread(target=_reader_loop, daemon=True)
        self._read_thread.start()

    def stop_inventory(self, delay: float = 0.05):
        """
        Sends Stop Inventory command (Cmd 0x28) to reader and waits for background thread to exit.
        Drains and clears input buffer to guarantee no residual frames remain.
        """
        if not self.is_reading:
            return
        self.is_reading = False
        
        with self._lock:
            if self.ser and self.ser.is_open:
                pkt_stop = build_frame("00", "28")
                self.ser.write(pkt_stop)
                self.ser.flush()

        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=0.3)

        if delay > 0:
            time.sleep(delay)

        with self._lock:
            if self.ser and self.ser.is_open and self.ser.in_waiting > 0:
                self.ser.reset_input_buffer()

    def close(self):
        """
        Safely stops inventory scanning and closes serial port connection.
        """
        self.stop_inventory()
        with self._lock:
            if self.ser and self.ser.is_open:
                self.ser.close()
                print("Reader connection closed.")

