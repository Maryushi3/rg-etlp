#!/usr/bin/env python3
"""
ETLP protocol implementation for LED displays.

Reverse-engineered from the original application (TrybETLP form).

Protocol:
  - RS485, 9600 8N1, half-duplex
  - STX=0x02, ETX=0x03
  - Command frames: STX + ASCII-hex-text + ETX
  - Data packet:    STX + CP852-text + CRC-hex + ETX
  - Address encoding: encoded = ((addr << 2) | 3), then 2-char uppercase hex
"""

import time
import serial
import glob
import sys
import os

# ═══════════════════════════════════════════════════════════════════════
# ETLP Protocol Reference
# ═══════════════════════════════════════════════════════════════════════
#
# Commands (host → display):
#   STX + ASCII-hex-text + ETX
#   where hex-text = AABBCCDD (8 hex chars, 4 bytes as text)
#     AA = encoded address  ((addr << 2) | 3)
#     BB = command (always 0x02)
#     CC = sub-command
#     DD = checksum = modulo-256 sum of ASCII bytes of first 6 chars
#
# Handshake sequence (all commands are host→display):
#   1. clear buffer:   {addr}020A{ck}
#   2. clear approved: 03020A36  (fixed addr 0)
#   3. ready for send: A3020036  (fixed addr 40)
#   4. data packet:    STX + CP852(payload) + CP852(crc_hex) + ETX
#   5. buffer ready:   0302082D  (fixed addr 0)
#   6. buffer approved:43020029  (fixed addr 16)
#   7. send buffer:    {addr}0208{ck}
#
# Data packet payload format (raw CP852 text):
#   {addr}FF3B\rNrWag\r{nr_wagonu}\rKierL3\r{nr_poc}\r
#   KierL4\r{stacja_pocz}\rKierL5\r{przebieg}\rKierL6\r{stacja_docel}\r
# Logical field naming (used in docs): L1=KierL3, L2=KierL4, L3=KierL5, L4=KierL6
#
# Responses (display → host, observed):
#   FF + STX + ASCII-hex-text + ETX
#   The 0xFF prefix distinguishes display responses from host commands.
#   Observed response types (all use addr 0x03):
#     - 03020A36  (ack after clear buffer)
#     - 03023B{ck} (ack after data packet)
#     - 030600... (longer status, includes ASCII model/version string)
#     - 0302082D  (ack after send buffer)
# ═══════════════════════════════════════════════════════════════════════

STX = bytes([0x02])
ETX = bytes([0x03])
ENCODING = "cp852"

# Serial frame limits for the data packet (STX + body + CRC + ETX).
MAX_FRAME_BYTES = 1002   # total frame size
MAX_BODY_BYTES = 998     # body bytes (excluding CRC)


def encode_address(addr: int) -> str:
    """Encode a logical address to the 2-char hex used on the wire."""
    return f"{((addr << 2) | 3) & 0xFF:02X}"


def crc_bytes(data: bytes) -> int:
    """Modulo-256 sum (used for data packet CRC)."""
    return sum(data) & 0xFF


def crc_hex_command(hex_text: str) -> str:
    """
    Compute the 2-char checksum for an ASCII-hex command frame.

    The checksum is the modulo-256 sum of the CP852 (ASCII) bytes
    of the first 6 hex characters (address + command + sub-command).

    Verified against all 6 known command frames in the original exe.
    """
    raw = hex_text[:6].encode(ENCODING)
    ck = sum(raw) & 0xFF
    return f"{ck:02X}"


def make_command_frame(hex_body: str) -> bytes:
    """Wrap a hex-body string in STX/ETX delimiters, CP852-encoded."""
    return STX + hex_body.encode(ENCODING) + ETX


def make_command_addr(addr: int, cmd_sub_hex: str) -> bytes:
    """
    Build a command frame with a configurable address.

    cmd_sub_hex is the 4 hex chars after the address (command + sub-command).
    E.g. "020A" for clear-buffer or "0208" for send-buffer.
    """
    addr_hex = encode_address(addr)
    first6 = addr_hex + cmd_sub_hex  # 6 hex chars → compute checksum
    ck = crc_hex_command(first6)
    return make_command_frame(first6 + ck)


def decode_text_escapes(text: str) -> str:
    """
    Convert \\xNN escape sequences to actual characters.

    Allows users to input OEM glyphs (0x01-0x1F) that would be hard to type
    directly, e.g. "\\x01" → smiley face character.
    """
    import re
    def _replace_hex(m):
        return chr(int(m.group(1), 16))
    return re.sub(r'\\x([0-9A-Fa-f]{2})', _replace_hex, text)


def sanitize_text(text: str) -> str:
    """
    Reject bytes that would break serial framing.

    Bytes 0x01-0x1F are displayable OEM glyphs on this hardware
    (e.g. 0x01 = smiley face). Only 0x02 (STX), 0x03 (ETX), and
    0x0D (CR) are prohibited because they conflict with the wire protocol.
    """
    encoded = text.encode(ENCODING)
    bad = [b for b in encoded if b in (0x02, 0x03, 0x0D)]
    if bad:
        chars = "".join(chr(b) for b in bad)
        raise ValueError(
            f"Framing bytes not allowed in display text: {chars!r}"
        )
    return text


def pad_nr_wagonu(val: str) -> str:
    """
    Pad wagon number to 3 chars with leading spaces for centering.

    The NrWag field area is ~3 monospace chars wide, right-aligned.
    Padding to exactly 3 total chars centers the text visually:
      1 digit  → "  {n}"  (2 leading spaces)
      2 digits → " {n}"   (1 leading space)
      3+ chars → as-is
    """
    if len(val) < 3:
        return val.rjust(3)
    return val


def make_data_packet(
    addr: int,
    nr_wagonu: str = "",
    nr_poc: str = "",
    stacja_pocz: str = "",
    przebieg: str = "",
    stacja_docel: str = "",
) -> bytes:
    """
    Build a data packet frame.

    Display layout (ETLP (132096-07), text alignment in parens):
        Row 1:     KierL3 / nr_poc       — train number (left-aligned)
        Row 2:     KierL4 / stacja_pocz  — departure station (left-aligned)
        Row 3:     KierL5 / przebieg     — route course (centered, scrolls)
        Row 4:     KierL6 / stacja_docel — destination station (right-aligned)
      Lower right: NrWag / nr_wagonu     — wagon number (right-aligned, ~3 char field,
                                           omitted if empty — text uses full width)

    Per-field max (compressible text, single field alone):
      KierL3–6: 716 chars (linear zone), 776–950 (recovery zone).
      Dead zone 717–775 always fails regardless of field count.
      Unique (raw) text: 332 chars shared across all scrolling fields.
    Total payload limit: 1002 bytes (STX + body + CRC + ETX).
    Body (without CRC) max = 998 bytes.
    Full compression model in compression.md.
    Scroll behavior: rows 1/3 same speed, rows 2/4 same speed, all start in sync.

    NrWag is optional — omit (empty string) to hide the bottom-right
    wagon-number block and let scrolling text use full display width.

    Format: STX + CP852(pakietString) + CP852(crc_hex) + ETX

    pakietString = header
                 + "NrWag" + "\\r" + nr_wagonu + "\\r"   (if nr_wagonu non-empty)
                 + "KierL3" + "\\r" + nr_poc + "\\r"
                 + "KierL4" + "\\r" + stacja_pocz + "\\r"
                 + "KierL5" + "\\r" + przebieg + "\\r"
                 + "KierL6" + "\\r" + stacja_docel + "\\r"

    where header = encode_address(addr) + "FF3B"
    """
    header = encode_address(addr) + "FF3B"
    parts = [header]
    if nr_wagonu:
        parts += ["NrWag", "\r", pad_nr_wagonu(nr_wagonu), "\r"]
    parts += [
        "KierL3", "\r", nr_poc, "\r",
        "KierL4", "\r", stacja_pocz, "\r",
        "KierL5", "\r", przebieg, "\r",
        "KierL6", "\r", stacja_docel, "\r",
    ]
    packet_text = "".join(parts)
    packet_bytes = packet_text.encode(ENCODING)
    if len(packet_bytes) > MAX_BODY_BYTES:
        raise ValueError(
            f"Data packet body too large: {len(packet_bytes)} bytes "
            f"(max {MAX_BODY_BYTES}). Shorten the text or use more "
            f"compressible/repetitive content."
        )
    ck_hex = f"{crc_bytes(packet_bytes):02X}"
    return STX + packet_bytes + ck_hex.encode(ENCODING) + ETX


# ── Fixed command frames (address-independent) ──────────────────────────
# These use hardcoded addresses (0, 40, 16) regardless of configured addr.
CMD_CLEAR_APPROVED = make_command_frame("03020A36")   # addr=0
CMD_READY_FOR_SEND = make_command_frame("A3020036")   # addr=40
CMD_BUFFER_READY    = make_command_frame("0302082D")   # addr=0
CMD_BUFFER_APPROVED = make_command_frame("43020029")   # addr=16
CMD_REBOOT          = make_command_frame("7F02384A")   # addr=31, power-cycle


def cmd_clear_buffer(addr: int = 16) -> bytes:
    """Clear display buffer frame (address-dependent)."""
    return make_command_addr(addr, "020A")


def cmd_send_buffer(addr: int = 16) -> bytes:
    """Send/show buffer frame (address-dependent)."""
    return make_command_addr(addr, "0208")


def send_frame(ser: serial.Serial, frame: bytes, label: str = "",
               read_response: bool = False) -> None:
    """Write a single frame to the serial port."""
    if label:
        print(f"  TX {label}: {frame.hex(' ').upper()}")
    else:
        print(f"  TX: {frame.hex(' ').upper()}")
    ser.write(frame)
    ser.flush()
    if read_response:
        _drain_response(ser)


def send_etlp(
    nr_wagonu: str = "",
    nr_poc: str = "",
    stacja_pocz: str = "",
    przebieg: str = "",
    stacja_docel: str = "",
    addr: int = 16,
    port: str | None = None,
    baud: int = 9600,
    read_resp: bool = False,
    check_ack: bool = False,
) -> bool:
    """
    Send ETLP departure data to the display.

    Replicates the exact sequence from the original application's wyslijEtlp_Click.

    Display layout (ETLP (132096-07), text alignment in parens):
      Row 1:     KierL3 / nr_poc       — train number (left-aligned)
      Row 2:     KierL4 / stacja_pocz  — departure station (left-aligned)
      Row 3:     KierL5 / przebieg     — route course (centered, scrolls)
      Row 4:     KierL6 / stacja_docel — destination station (right-aligned)
      Lower right: NrWag / nr_wagonu   — wagon number (right-aligned, ~3 char field, auto-centered;
                                         omitted if empty — text uses full width)

    Dual limits (exceeding locks display — needs reset/power-cycle):
      1) Frame size: max 1002 bytes total (STX + body + CRC + ETX).
         Body (without CRC) max = 998 bytes.
      2) Internal scrolling text buffer: 332 units shared across ALL
         scrolling fields (KierL3/4/5/6 = logical L1-L4). Compression
         is NOT RLE — see compression.md for details.

    Per-field guidance (compressible text):
      Single field alone: 716 chars (linear zone), 776–950 (recovery zone).
      Dead zone 717–775 always fails regardless of field count.
      Multiple fields: shared buffer — see compression.md for limits.
      Unique (raw) text: 332 chars total across all fields.
      NrWag: ~3 (omit for full-width scrolling text)

    Scroll behavior: rows 1/3 same speed, rows 2/4 same speed, all start in sync.
    NrWag centering: nr_wagonu is auto-padded to 3 chars via pad_nr_wagonu().

    Args:
        nr_wagonu:   Wagon number (auto-padded to 3 chars for centering; omit/empty to hide)
        nr_poc:      Train number (nrPoc / KierL3 = logical L1, ~950 all-same / 332 unique)
        stacja_pocz: Departure station (stacjaPocz / KierL4 = logical L2, ~950 / 332)
        przebieg:    Route number (przebieg / KierL5 = logical L3, ~950 / 332)
        stacja_docel: Destination station (stacjaDocel / KierL6 = logical L4, ~950 / 332)
        addr:        Display address (default 16)
        port:        Serial port path (auto-detect if None)
        baud:        Baud rate (default 9600)
        read_resp:   Read response after each frame
        check_ack:   Verify data ACK (03023B3A) — returns False if data rejected

    Returns:
        True if data was accepted (or check_ack=False), False if ACK check failed.
    """
    nr_wagonu = sanitize_text(decode_text_escapes(nr_wagonu))
    nr_poc = sanitize_text(decode_text_escapes(nr_poc))
    stacja_pocz = sanitize_text(decode_text_escapes(stacja_pocz))
    przebieg = sanitize_text(decode_text_escapes(przebieg))
    stacja_docel = sanitize_text(decode_text_escapes(stacja_docel))

    ser = _open_port(port, baud)
    try:
        data_pkt = make_data_packet(addr, nr_wagonu, nr_poc, stacja_pocz, przebieg, stacja_docel)

        print(f"ETLP send (addr={addr}):")
        print(f"  nrWagonu={nr_wagonu!r}, nrPoc={nr_poc!r}")
        print(f"  stacjaPocz={stacja_pocz!r}, przebieg={przebieg!r}, stacjaDocel={stacja_docel!r}")

        # Frames 1-4: clear buffer, clear approved, ready for send, data packet
        frames_1_4 = [
            ("clear buffer", cmd_clear_buffer(addr)),
            ("clear approved", CMD_CLEAR_APPROVED),
            ("ready for send", CMD_READY_FOR_SEND),
            ("data packet", data_pkt),
        ]
        for label, frame in frames_1_4:
            print(f"  TX {label}: {frame.hex(' ').upper()}")
            ser.write(frame)
        ser.flush()

        # RS485 turnaround + display processing gap
        time.sleep(0.050)

        data_ack_ok = True
        if check_ack:
            ser.timeout = 0.3
            resp = b""
            while True:
                chunk = ser.read(1024)
                if not chunk:
                    break
                resp += chunk
            if resp:
                print(f"  RX: {resp.hex(' ').upper()}")
            if b"03023B3A" not in resp:
                print("  WARNING: data ACK not received — content may have been rejected (buffer overflow)")
                data_ack_ok = False

        # Frames 5-7: buffer ready, buffer approved, send buffer
        frames_5_7 = [
            ("buffer ready", CMD_BUFFER_READY),
            ("buffer approved", CMD_BUFFER_APPROVED),
            ("send buffer", cmd_send_buffer(addr)),
        ]
        for label, frame in frames_5_7:
            print(f"  TX {label}: {frame.hex(' ').upper()}")
            ser.write(frame)
        ser.flush()

        if read_resp:
            _drain_response(ser, timeout=0.2)

        print("ETLP send complete.")
        return data_ack_ok
    finally:
        ser.close()


def clear_etlp(addr: int = 16, port: str | None = None, baud: int = 9600,
               read_resp: bool = False) -> None:
    """
    Clear the ETLP display.

    Replicates the exact sequence from the original application's czysc_Click.
    (Same as send_etlp but without the data packet frame.)
    """
    ser = _open_port(port, baud)
    try:
        print(f"ETLP clear (addr={addr}):")

        # Frames 1-3: clear buffer, clear approved, ready for send
        frames_1_3 = [
            ("clear buffer", cmd_clear_buffer(addr)),
            ("clear approved", CMD_CLEAR_APPROVED),
            ("ready for send", CMD_READY_FOR_SEND),
        ]
        for label, frame in frames_1_3:
            print(f"  TX {label}: {frame.hex(' ').upper()}")
            ser.write(frame)
        ser.flush()

        # RS485 turnaround gap
        time.sleep(0.050)

        # Frames 4-6: buffer ready, buffer approved, send buffer
        frames_4_6 = [
            ("buffer ready", CMD_BUFFER_READY),
            ("buffer approved", CMD_BUFFER_APPROVED),
            ("send buffer", cmd_send_buffer(addr)),
        ]
        for label, frame in frames_4_6:
            print(f"  TX {label}: {frame.hex(' ').upper()}")
            ser.write(frame)
        ser.flush()

        if read_resp:
            _drain_response(ser, timeout=0.2)

        print("ETLP clear complete.")
    finally:
        ser.close()


def reboot_etlp(port: str | None = None, baud: int = 9600,
                read_resp: bool = False) -> None:
    """
    Send reset/power-cycle command to the display.

    Uses a fixed address of 31 (encoded as 0x7F). The display accepts
    commands immediately but won't show data for ~15s after boot —
    either wait or use send_etlp/clear_etlp after that window.

    Command frame: `STX + "7F02384A" + ETX`.
    Discovered via the `ramkareboot` field in the original application's Form1.
    """
    ser = _open_port(port, baud)
    try:
        print("ETLP reset:")
        send_frame(ser, CMD_REBOOT, "reset cmd", read_resp)
        print("ETLP reset sent. Send data immediately to skip the boot sequence.")
    finally:
        ser.close()


def _drain_response(ser: serial.Serial, timeout: float = 0.2) -> bytes:
    """Read any pending response data from the display."""
    ser.timeout = timeout
    data = b""
    while True:
        chunk = ser.read(1024)
        if not chunk:
            break
        data += chunk
    if data:
        print(f"  RX: {data.hex(' ').upper()}")
    return data


def listen(port: str | None = None, baud: int = 9600,
           timeout: float = 10) -> None:
    """Listen for data from the display."""
    ser = _open_port(port, baud)
    try:
        print(f"Listening on {ser.port} for {timeout}s...")
        ser.timeout = timeout
        data = ser.read(4096)
        if data:
            print(f"RX ({len(data)} bytes): {data.hex(' ').upper()}")
            try:
                print(f"RX (text): {data.decode('cp852', errors='replace')}")
            except Exception:
                pass
        else:
            print("No data received.")
    finally:
        ser.close()


def _detect_port() -> str:
    """Auto-detect the serial port (Mac / Linux)."""
    # Common patterns for USB CDC ACM / serial adapters
    patterns = [
        "/dev/tty.usbmodem*",
        "/dev/ttyACM*",
        "/dev/ttyUSB*",
        "/dev/tty.SLAB_USBtoUART*",
        "/dev/tty.usbserial*",
    ]
    for pattern in patterns:
        ports = sorted(glob.glob(pattern))
        if ports:
            return ports[0]
    print("No serial port found. Specify --port manually.", file=sys.stderr)
    sys.exit(1)


def _open_port(port: str | None, baud: int) -> serial.Serial:
    """Open and configure the serial port (9600 8N1 no handshake)."""
    if port is None:
        port = _detect_port()
    print(f"Opening {port} @ {baud} 8N1")
    ser = serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=False,
        rtscts=False,
        timeout=1,
    )
    return ser


def _verify(addr: int = 17) -> None:
    """Verify computed frames match the original exe for a given address."""
    enc = encode_address(addr)
    print(f"Address {addr} → encoded {enc}")
    print()

    # Expected values from original exe (address 17)
    if addr == 17:
        expected = {
            "clear_buf": "47020A3E",
            "send_buf": "47020835",
        }
    elif addr == 16:
        expected = {
            "clear_buf": "43020A3A",  # computed, not from original
            "send_buf": "43020831",   # computed, not from original
        }
    else:
        expected = {}

    def body_text(frame: bytes) -> str:
        """Extract the hex-body text from a framed command (STX..ETX)."""
        return frame[1:-1].decode("ascii")

    def check(name: str, got: str, exp: str | None = None) -> None:
        label = f"  {name:20s}"
        if exp and got != exp:
            print(f"{label}{got}  ← MISMATCH (expected {exp})")
        else:
            print(f"{label}{got}" + ("  ✓" if exp and got == exp else ""))

    check("clear buffer body", body_text(cmd_clear_buffer(addr)), expected.get("clear_buf"))
    check("send buffer body",  body_text(cmd_send_buffer(addr)), expected.get("send_buf"))

    check("clear approved (fixed)", body_text(CMD_CLEAR_APPROVED))
    check("ready for send (fixed)", body_text(CMD_READY_FOR_SEND))
    check("buffer ready (fixed)",   body_text(CMD_BUFFER_READY))
    check("buffer approved (fixed)", body_text(CMD_BUFFER_APPROVED))

    # Data packet CRC check
    pkt = make_data_packet(addr, "TEST", "123", "StationA", "R45", "StationB")
    payload = pkt[1:-1]
    crc_stored = payload[-2:]
    crc_computed = f"{crc_bytes(payload[:-2]):02X}".encode("ascii")
    print(f"  data packet CRC:     {crc_stored.decode('ascii')} (computed: {crc_computed.decode('ascii')})",
          "✓" if crc_stored == crc_computed else "✗")


# ── CLI ─────────────────────────────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Control an ETLP LED display over RS485",
    )
    parser.add_argument("--addr", type=int, default=16, help="Display address (default: 16)")
    parser.add_argument("--port", help="Serial port (auto-detect if omitted)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--read", action="store_true", default=False,
                        help="Read response data after each frame")

    act = parser.add_mutually_exclusive_group(required=False)
    act.add_argument("--clear", action="store_true", help="Clear display")
    act.add_argument("--reboot", action="store_true", help="Power-cycle the display")
    act.add_argument("--listen", action="store_true", help="Listen for display responses")
    act.add_argument("--verify", action="store_true", help="Verify computed frames against known values")

    parser.add_argument("--wag", "--wagon", default="", help="Wagon number")
    parser.add_argument("--l1", "--train", default="", help="Line 1 = KierL3 (train number)")
    parser.add_argument("--l2", "--departure", default="", help="Line 2 = KierL4 (departure station)")
    parser.add_argument("--l3", "--route", default="", help="Line 3 = KierL5 (route course)")
    parser.add_argument("--l4", "--destination", default="", help="Line 4 = KierL6 (destination station)")

    args = parser.parse_args()

    if args.clear:
        clear_etlp(addr=args.addr, port=args.port, baud=args.baud,
                   read_resp=args.read)
    elif args.reboot:
        reboot_etlp(port=args.port, baud=args.baud, read_resp=args.read)
    elif args.listen:
        listen(port=args.port, baud=args.baud)
    elif args.verify:
        _verify(args.addr)
    else:
        ok = send_etlp(
            args.wag, args.l1, args.l2, args.l3, args.l4,
            addr=args.addr, port=args.port, baud=args.baud,
            read_resp=args.read, check_ack=args.read,
        )
        if args.read and not ok:
            print("Data was rejected by display (buffer overflow or frame too large)")


if __name__ == "__main__":
    main()
