#!/usr/bin/env python3
"""Web UI for the ETLP LED display.

Usage:
    python3 app.py --port /dev/tty.usbmodemXXXX
    python3 app.py --port /dev/tty.usbmodemXXXX --addr 16 --baud 9600
"""

import sys
import os
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify
from etlp_send import send_etlp, clear_etlp, sanitize_text, decode_text_escapes

import argparse

app = Flask(__name__)

# Populated by main() from CLI arguments. Defaults are safe for import-only
# usage (e.g., from a WSGI server or test harness).
SERIAL_PORT = None
ADDR = 16
BAUD = 9600
_serial_lock = threading.Lock()

# 332 chars is the safe limit for unique (uncompressible) text across all
# four scrolling fields. Repetitive text can be much longer thanks to the
# display's internal compression, but this is the conservative default for a
# web form where users are unlikely to craft compressor-friendly strings.
MAX_TOTAL_CHARS = 332


def send_to_display(wag="", l1="", l2="", l3="", l4=""):
    # Decode \xNN escapes before checking length / sending
    wag = decode_text_escapes(wag)
    l1 = decode_text_escapes(l1)
    l2 = decode_text_escapes(l2)
    l3 = decode_text_escapes(l3)
    l4 = decode_text_escapes(l4)
    total = len(l1) + len(l2) + len(l3) + len(l4)
    if total > MAX_TOTAL_CHARS:
        return False, (
            f"Total length {total} exceeds {MAX_TOTAL_CHARS} safe unique-text chars. "
            "Use shorter or more repetitive text."
        )
    try:
        wag, l1, l2, l3, l4 = (sanitize_text(x) for x in (wag, l1, l2, l3, l4))
        with _serial_lock:
            ok = send_etlp(wag, l1, l2, l3, l4, addr=ADDR, port=SERIAL_PORT, baud=BAUD,
                           check_ack=True)
        if not ok:
            return False, "Data rejected by display (buffer overflow or frame too large)"
        return True, "Sent successfully"
    except Exception as e:
        return False, str(e)


def clear_display():
    try:
        with _serial_lock:
            clear_etlp(addr=ADDR, port=SERIAL_PORT, baud=BAUD)
        return True, "Display cleared"
    except Exception as e:
        return False, str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/send", methods=["POST"])
def send():
    wag = request.form.get("wag", "")
    l1 = request.form.get("l1", "")
    l2 = request.form.get("l2", "")
    l3 = request.form.get("l3", "")
    l4 = request.form.get("l4", "")
    ok, msg = send_to_display(wag, l1, l2, l3, l4)
    return jsonify(success=ok, message=msg)


@app.route("/clear", methods=["POST"])
def clear():
    ok, msg = clear_display()
    return jsonify(success=ok, message=msg)


def _parse_args():
    parser = argparse.ArgumentParser(description="Web UI for ETLP LED display")
    parser.add_argument("--port", required=True, help="Serial port (e.g. /dev/tty.usbmodemXXXX)")
    parser.add_argument("--addr", type=int, default=16, help="Display address (default: 16)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--host", default="127.0.0.1", help="Listen address (default: 127.0.0.1)")
    parser.add_argument("--http-port", type=int, default=8080, help="HTTP port (default: 8080)")
    return parser.parse_args()


def main():
    global SERIAL_PORT, ADDR, BAUD
    args = _parse_args()
    SERIAL_PORT = args.port
    ADDR = args.addr
    BAUD = args.baud
    app.run(host=args.host, port=args.http_port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
