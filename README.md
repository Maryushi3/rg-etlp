# rg-etlp — ETLP LED Display Control

Python library and protocol documentation for controlling R&G Mielec ETLP (132096-07) LED train signage over RS485.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Send departure data (numbered or semantic flags, mixable)
python3 etlp_send.py --port /dev/tty.usbmodemXXXX --l1 123 --l2 WARSZAWA --l3 R-7 --l4 KRAKOW --wag 001
python3 etlp_send.py --port /dev/tty.usbmodemXXXX --train 123 --departure WARSZAWA --route R-7 --destination KRAKOW

# Clear display
python3 etlp_send.py --port /dev/tty.usbmodemXXXX --clear

# Listen for display responses
python3 etlp_send.py --port /dev/tty.usbmodemXXXX --listen

# Verify computed protocol frames against known values
python3 etlp_send.py --verify

# Web UI (auto-detect port, opens at http://127.0.0.1:8080)
cd web-ui && ./start.sh
```

## Protocol

See [`protocol.md`](protocol.md) for the full protocol reference — frame formats, handshake sequences, address encoding, checksum calculation, display responses, and the dual limits (1002-byte frame, 332-unit internal scroll buffer).

## Internal Buffer Compression

The display compresses scrolling text in its internal buffer using a **non-RLE** algorithm (likely block/dictionary-based). Full empirical analysis in [`compression.md`](compression.md). Key findings:

- **Not RLE**: ABABAB compresses same as AAAAAA
- Raw capacity: **332 characters** of unique text
- Repetitive text compresses up to **25:1** (at 400 chars), degrading to **4.4:1** (at 799 chars)
- **Five regimes**: raw (1–332), mini dead zone (333–399), linear (400–716), buffer dead zone (717–775), recovery (776–950)
- **Two-pool model**: Pool A (L1+L3, fast scroll) and Pool B (L2+L4, slow scroll) share the buffer

## Device Details

| Parameter | Value |
|---|---|
| Model | ETLP (132096-07) |
| Firmware | ETLP/OP-41, identifier V1-Y |
| Production | 2009-03 |
| Power | 24 V DC (works at 20 V), 6 A, IP40 |
| Consumption | 20 W idle, 30 W active, 80 W peak |
| Interface | RS485 half-duplex, 9600 8N1 |
| Encoding | CP852 (DOS Latin-2) |
| Address | 16 (configurable) |

## Files

| File | Description |
|---|---|
| `etlp_send.py` | Working Python implementation |
| `protocol.md` | Protocol specification |
| `compression.md` | Internal buffer compression analysis |
| `web-ui/` | Flask web interface with auto-detect start script |
| `tests/` | Unit tests for protocol frames and web UI importability |
| `requirements.txt` | Python dependencies |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Thanks

- Mitsumi, HiszpanInk, LirekPL ([rg-screens-things](https://github.com/HiszpanInk/rg-screens-things)) — protocol notes, prior reverse-engineering, and of course providing me with a display
- DeepSeek V4 (Free & Pro) — LLM assistance throughout the reverse-engineering research
