#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PORT=""
if [ "${1:-}" != "" ] && [ -e "${1:-}" ]; then
    PORT="$1"
    shift
fi

if [ -z "$PORT" ]; then
    for pattern in /dev/tty.usbmodem* /dev/ttyACM* /dev/ttyUSB* /dev/tty.SLAB_USBtoUART* /dev/tty.usbserial*; do
        for p in $pattern; do
            if [ -e "$p" ]; then PORT="$p"; break 2; fi
        done
    done
fi

if [ -z "$PORT" ]; then
    echo "No RS485 device found in /dev" >&2
    echo "Usage: ./start.sh [/dev/ttyXXX]" >&2
    exit 1
fi

echo "Device: $PORT"
echo "Starting at http://127.0.0.1:8080"
exec python3 app.py --port "$PORT" "$@"
