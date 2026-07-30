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
from typing import Callable, Optional


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
        if not self.ser or not self.ser.is_open:
            return "Not Connected"
            
        # Build frame: MsgType=00, Cmd=03, Data=00 (Hardware Version requested)
        pkt = build_frame("00", "03", "00")
        self.ser.write(pkt)
        self.ser.flush()
        time.sleep(0.1)
        
        # Read response packet
        if self.ser.in_waiting > 0:
            resp = self.ser.read(self.ser.in_waiting)
            if len(resp) >= 7 and resp[0] == 0xAA and resp[-1] == 0xDD:
                data_len = (resp[3] << 8) | resp[4]
                payload = resp[5:5+data_len]
                # Decode ASCII version string skipping status bytes
                return payload[2:].decode('ascii', errors='ignore').strip()
        return "IN-R200 UHF Reader"

    def set_rf_power(self, power_dbm: float = 26.0) -> bool:
        """
        Configures reader RF Output Power in dBm (e.g., 26.0 dBm).
        
        Protocol encoding:
        Power in dBm * 100 (e.g., 26.0 dBm = 2600 = 0x0A28)
        Cmd = 0xB6
        """
        if not self.ser or not self.ser.is_open:
            return False
            
        power_val = int(power_dbm * 100)
        data_hex = f"{power_val:04X}"
        pkt = build_frame("00", "B6", data_hex)
        
        self.ser.write(pkt)
        self.ser.flush()
        time.sleep(0.1)
        
        if self.ser.in_waiting > 0:
            self.ser.read(self.ser.in_waiting)
            return True
        return False

    def start_inventory(self, tag_callback: Callable[[str, int, str], None]):
        """
        Launches background thread to continuously scan for RFID tags.
        
        Parameters:
        - tag_callback: Function called when a tag is read -> callback(epc: str, rssi: int, pc: str)
        """
        if self.is_reading:
            return
        self.is_reading = True
        
        # Cmd 0x27 = Read Multi Tag, Payload = 0000FFFF (65535 rounds per burst)
        pkt_start = build_frame("00", "27", "0000FFFF")

        def _reader_loop():
            """
            Background worker thread function with Watchdog mechanism.
            Continuously reads incoming serial bytes and parses AA...DD frames.
            """
            buffer = bytearray()
            last_cmd_sent = 0
            
            while self.is_reading:
                now = time.time()
                
                # WATCHDOG MECHANISM:
                # If no tag data received for 1.0 second (meaning the batch finished),
                # re-trigger the inventory command so reading runs continuously forever.
                if now - last_cmd_sent > 1.0:
                    if self.ser and self.ser.is_open:
                        self.ser.write(pkt_start)
                        self.ser.flush()
                        last_cmd_sent = now

                # Check if serial data is available in buffer
                if self.ser and self.ser.in_waiting > 0:
                    buffer.extend(self.ser.read(self.ser.in_waiting))
                    
                    # Search and extract complete frames (0xAA header to 0xDD ender)
                    while len(buffer) > 0:
                        aa_pos = buffer.find(0xAA)
                        if aa_pos == -1:
                            buffer.clear()
                            break
                            
                        dd_pos = buffer.find(0xDD, aa_pos)
                        if dd_pos != -1:
                            # Extract full packet byte slice
                            pkt = bytes(buffer[aa_pos:dd_pos+1])
                            buffer = buffer[dd_pos+1:]
                            
                            # Verify if packet is a Tag Inventory Report (Cmd 0x22 or 0x27)
                            if len(pkt) >= 8 and pkt[2] in (0x22, 0x27):
                                data_len = (pkt[3] << 8) | pkt[4]
                                data = pkt[5:5+data_len]
                                
                                if len(data) >= 5:
                                    # Reset watchdog timer because reader is actively transmitting
                                    last_cmd_sent = time.time()
                                    
                                    # Parse Data Payload Fields:
                                    # Byte 0      : RSSI (Received Signal Strength Indicator)
                                    # Bytes 1..2  : PC (Protocol Control word, e.g. 3400)
                                    # Bytes 3..N-2: EPC (Electronic Product Code, 96-bit / 24 hex characters)
                                    rssi = data[0]
                                    pc = data[1:3].hex().upper()
                                    epc = data[3:-2].hex().upper() if len(data) > 5 else data[3:].hex().upper()
                                    
                                    if epc:
                                        # Invoke user callback with parsed tag details
                                        tag_callback(epc, rssi, pc)
                        else:
                            break
                time.sleep(0.01)

        # Spawn background daemon thread for non-blocking execution
        self._read_thread = threading.Thread(target=_reader_loop, daemon=True)
        self._read_thread.start()

    def stop_inventory(self):
        """
        Sends Stop Inventory command (Cmd 0x28) to reader and stops background thread.
        """
        if not self.is_reading:
            return
        self.is_reading = False
        
        if self.ser and self.ser.is_open:
            # Cmd 0x28 = Stop Read Multi Tag
            pkt_stop = build_frame("00", "28")
            self.ser.write(pkt_stop)
            self.ser.flush()
            time.sleep(0.1)
            if self.ser.in_waiting > 0:
                self.ser.read(self.ser.in_waiting)

    def close(self):
        """
        Safely stops inventory scanning and closes serial port connection.
        """
        self.stop_inventory()
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Reader connection closed.")
