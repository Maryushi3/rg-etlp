# ETLP Protocol — LED Display

Reverse-engineered from the original application (TrybETLP form, decompiled via `monodis`).

## Hardware Reference

Tested display: **ETLP (132096-07)** (R&G, address **16**)
- Software: ETLP/OP-41, identifier V1-Y
- Production date: 2009-03
- Power: 24 V DC, 6 A, IP40 (works fine at 20 V)
- Power consumption: 20 W idle (blank), 30 W showing data, 80 W peak during boot sequence

## Physical Layer

| Parameter | Value |
|-----------|-------|
| Interface | RS485 half-duplex via USB CDC ACM |
| Baud rate | 9600 |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Flow control | None |
| Encoding | CP852 (DOS Latin-2) for all string/char data |

## Delimiters

- **STX** = `0x02` — start of frame
- **ETX** = `0x03` — end of frame

## Address Encoding

Logical address `addr` (0–63) is encoded to a wire byte:

```
encoded = ((addr << 2) | 3) & 0xFF
```

On the wire, the encoded byte is represented as a **2-character uppercase hex string**.

Examples:

| Logical addr | Encoded byte | Hex text |
|-------------|-------------|----------|
| 0 | 0x03 | `03` |
| 16 | 0x43 | `43` |
| 17 | 0x47 | `47` |
| 40 | 0xA3 | `A3` |

## Frame Types

### 1. Command Frames (host → display)

```
STX + ASCII_HEX_TEXT + ETX
```

The ASCII hex body is exactly **8 hex characters** (4 bytes as text):

```
AABBCCDD
```

| Field | Bytes | Meaning |
|-------|-------|---------|
| `AA` | 2 hex | Encoded address (see above) |
| `BB` | 2 hex | Command byte (always `02`) |
| `CC` | 2 hex | Sub-command |
| `DD` | 2 hex | Checksum |

**Checksum:** Modulo-256 sum of the CP852 (ASCII) bytes of `AABBCC` (first 6 hex chars). E.g. for body `43020A3A`:

```
'4'(0x34) + '3'(0x33) + '0'(0x30) + '2'(0x32) + '0'(0x30) + 'A'(0x41) = 0x13A
0x13A mod 256 = 0x3A  →  checksum = "3A"
```

### 2. Data Packet (host → display)

```
STX + CP852(PAYLOAD_TEXT) + CP852(CRC_HEX) + ETX
```

The payload is raw CP852-encoded text (not hex-encoded). The CRC is appended as a 2-char uppercase hex string, also CP852-encoded.

**CRC:** Modulo-256 sum of all CP852 bytes of `PAYLOAD_TEXT` (same algorithm as the modulo-256 used for command frames, but operating on raw bytes not ASCII chars — for ASCII-only payloads the result is the same).

### 3. Display Responses (display → host)

```
FF + STX + ASCII_HEX_TEXT + ETX
```

Same format as command frames but prefixed with `0xFF`. All observed responses use address `0x03` regardless of the display's configured address.

### CP852 Encoding

The protocol uses **CP852** (DOS Latin-2) for all text data. Python's built-in `cp852` codec is used for encode/decode.

**Not all CP852 glyphs render correctly on the display.** The character ROM in the ETLP hardware may differ from standard CP852 for some code points.

Bytes `0x01`–`0x1F` are **displayable OEM glyphs** (e.g. `0x01` = smiley face, `0x0F` = centered circle). They are NOT interpreted as control codes. Only `0x02` (STX), `0x03` (ETX), and `0x0D` (CR / `\r`) serve as framing/control bytes. Escape sequences `\xNN` are supported in the Python library.

For response frames sent by the display, see [Responses](#responses).

## Handshake Sequences

### Send Data (`send_etlp` in Python, `wyslijEtlp_Click` in exe)

Sends 7 frames in order. The original C# exe used conservative delays (200ms between commands, 800ms after data). Empirical testing shows all inter-command delays can be **eliminated entirely** (pipelined back-to-back) and the data-processing delay reduced to as little as **2ms**:

```
Step  Host sends                    Delay after (original)  (minimum)
────  ──────────────────────────    ─────────────────────  ─────────
  1   {addr}02 0A {ck}              200ms                  0ms
  2   03 02 0A 36                    200ms                  0ms
  3   A3 02 00 36                    200ms                  0ms
  4   [DATA PACKET]                  800ms                  2–10ms
  5   03 02 08 2D                    200ms                  0ms
  6   43 02 00 29                    200ms                  0ms
  7   {addr}02 08 {ck}              —                      —
```

**Benchmark results** (fire-and-forget, 50ms data delay safety margin):
- Best send time: **52ms** (includes USB serial buffering at 9600 baud)
- Average send time: **72ms**
- Rate: **~14 sends/s** (vs ~0.77 sends/s with original delays)

Subsequent commands can be sent without intermediate reads — the display buffers them internally. For ACK verification, read responses ~100ms after the data packet (display responds within ~50ms of receiving it).

### Clear Display (`clear_etlp` in Python, `czysc_Click` in exe)

Same as send but **without the data packet** (step 4):

```
Step  Host sends                    Delay after
────  ──────────────────────────    ───────────
  1   {addr}02 0A {ck}              200ms
  2   03 02 0A 36                    200ms
  3   A3 02 00 36                    200ms
  4   03 02 08 2D                    200ms
  5   43 02 00 29                    200ms
  6   {addr}02 08 {ck}              —
```

## Data Packet Format

```
{addr}FF3B\rNrWag\r{nrWagonu}\rKierL3\r{nrPoc}\r
KierL4\r{stacjaPocz}\rKierL5\r{przebieg}\rKierL6\r{stacjaDocel}\r
```

| Field | Key | Display position | Meaning |
|-------|-----|------------------|---------|
| `{addr}FF3B` | — | — | Data packet header |
| `NrWag` | Key | Lower right corner | Wagon number |
| `{nrWagonu}` | Value | Lower right corner | Wagon number |
| `KierL3` | Key | Row 1 | Train number label (logical L1) |
| `{nrPoc}` | Value | Row 1 | Train number |
| `KierL4` | Key | Row 2 | Departure station label (logical L2) |
| `{stacjaPocz}` | Value | Row 2 | Departure station |
| `KierL5` | Key | Row 3 | Route course label (logical L3) |
| `{przebieg}` | Value | Row 3 | Route course (scrolls if long) |
| `KierL6` | Key | Row 4 | Destination station label (logical L4) |
| `{stacjaDocel}` | Value | Row 4 | Destination station |

**Logical naming:** This document uses **L1–L4** for the scrolling fields, mapped as:
- L1 = `KierL3` (train number), L2 = `KierL4` (departure),
- L3 = `KierL5` (route), L4 = `KierL6` (destination).

The `KierL3`/`KierL4`/`KierL5`/`KierL6` keys are **mandatory delimiters** — omitting or reordering them causes content to appear in the wrong row or not at all. The display parses fields positionally by scanning for these exact strings.

`KierL1` and `KierL2` are **not used** by this display model, but are believed to control the top two rows on other R&G Mielec devices sharing the same RS485 bus. When sending data to an ETLP, these keys should be omitted or left empty to avoid unintended side effects on adjacent units.

**Text alignment (per row):**

| Row | Alignment |
|-----|-----------|
| Row 1 (L1) | Left-aligned |
| Row 2 (L2) | Left-aligned |
| Row 3 (L3) | Centered |
| Row 4 (L4) | Right-aligned |
| NrWag | Right-aligned |

Each key-value pair is separated by `\r` (0x0D). The header `{addr}FF3B` is concatenated directly with the first key `NrWag` (no separator between them).

CRC is computed over the entire payload text (header + keys + values + delimiters) and appended as a 2-char uppercase hex string before ETX.

**Dual limits (frame size + internal scroll text buffer):**

Fields exceeding either limit cause the display to acknowledge all commands, play the curtain animation, then go blank. Recovery requires a reset or power cycle.

1) **Frame size limit: 1002 bytes** total (STX + CP852-body + CRC + ETX). Body (without CRC) max = 998 bytes. For a single scrolling field with minimal others: **716 chars** (linear zone), dead zone 717–775 (always fails), or **776–950** (recovery zone). Raw/unique text max = 332 chars across all fields.

2) **Internal scrolling text buffer: 332 units** shared across all four scrolling fields. The display uses a **content-dependent compression** that is **NOT run-length encoding**.

   - **Raw mode** (no compressible pattern): text stored at 1 unit/char. Max 332 chars (333 fails).
   - **Compressible patterns** (repeating chars, alternating patterns, mixed runs): the display applies a block/dictionary-based compression. Compression ratio degrades with length — from ~25:1 at 400 chars to ~4.4:1 at 799 chars.
   - A single interloper in a long run **costs nothing** extra.
    - **Dead zone (717–775):** runs of identical chars in this range fail alone — the primary compression scheme overflows the buffer and no fallback activates.
    - **Recovery zone (≥ 776):** a different compression scheme activates, fitting runs up to ~950 chars within the buffer.

   Because the buffer is shared, loading 332 unique chars into one field uses the entire buffer. To populate multiple long fields simultaneously, use repetitive text.

   See `compression.md` in this repository for the detailed empirical data and measurement methodology.

NrWag is **optional** — omitting the `NrWag\r...\r` pair from the data packet
hides the bottom-right wagon-number block (and its pictogram), allowing scrolling
text to use the full display width. Observed on ETLP (132096-07): with NrWag
absent, rows 1–4 scroll edge-to-edge with no static overlay in the lower right.

NrWag is static at ~3 characters (right-aligned; pad to 3 chars with leading spaces to center visually).

**Scrolling behavior:**
- All scrolling rows start in sync at the right edge of the display.
- Rows 1 and 3 scroll at the same speed.
- Rows 2 and 4 scroll at the same speed.
- NrWag does not scroll (static, right-aligned).

| Field | Display row | Max identical chars (single field) | Max unique chars | Scrolling |
|-------|-------------|-------------------------------------|-------------------|-----------|
| KierL3 (train#) | Row 1 | 716 (linear) / 776–950 (recovery) | 332 | Yes |
| KierL4 (departure) | Row 2 | 716 (linear) / 776–950 (recovery) | 332 | Yes |
| KierL5 (route course) | Row 3 | 716 (linear) / 776–950 (recovery) | 332 | Yes |
| KierL6 (destination) | Row 4 | 716 (linear) / 776–950 (recovery) | 332 | Yes |
| NrWag (wagon#) | Lower right | ~3 | ~3 | No |

Dead zone 717–775 fails for any single field regardless of content. When multiple fields are populated, the two-pool model applies (Pool A = L1+L3, Pool B = L2+L4) with shared 332-unit buffer. See `compression.md`.

## Command Reference

### Address-dependent frames

These change when the display address changes:

| Name | Hex pattern | Sub-command |
|------|-------------|-------------|
| Clear buffer | `{addr} 02 0A {ck}` | `0A` |
| Send buffer | `{addr} 02 08 {ck}` | `08` |
| Data header | `{addr} FF 3B` | (no checksum, part of data packet) |

### Fixed-address frames

These use hardcoded addresses regardless of display configuration:

| Name | Full hex body | Address | Meaning |
|------|-------------|---------|---------|
| Clear approved | `03020A36` | 0 | Acknowledges buffer clear |
| Ready for send | `A3020036` | 40 | Signals ready for data |
| Buffer ready | `0302082D` | 0 | Signals buffer loaded |
| Buffer approved | `43020029` | 16 | Acknowledges buffer ready |

## Responses

The display sends back responses prefixed with `0xFF`. These were observed when using the `--read` flag:

```
After clear buffer:   FF 02 30 33 30 32 30 41 33 36 03
After data packet:    FF 02 30 33 30 32 33 42 33 41 03
After buffer approved:FF 02 30 33 30 36 30 30 4C 49 38 32 32 38 03
After send buffer:    FF 02 30 33 30 32 30 38 32 44 03
```

Interpretation (all hex-encoded like commands, same STX/ETX framing, prefixed by `0xFF`):

| After host sends | Response (hex text) | Decoded meaning |
|-----------------|---------------------|-----------------|
| Clear buffer | `03020A36` | Clear approved echo (cmd `02`, sub `0A`) |
| Data packet | `03023B3A` | Data received ACK (cmd `02`, sub `3B`) |
| Buffer approved | `0306004C4938323238` | Status response (cmd `06`, sub `00`) + ASCII `LI8228` |
| Send buffer | `0302082D` | Buffer ready echo (cmd `02`, sub `08`) |

All responses use address `0x03`, independent of the display's configured address.

### The `LI8228` status response

The longer response (`030600` + `LI8228`) appears after the "buffer approved" step. The `03 06 00` prefix looks like a command header (address `03`, command `06`, sub `00`), followed by 6 bytes of literal ASCII text.

`LI8228` does not directly match any text from the device labels (model `ETLP (132096-07)`, firmware `ETLP/OP-41` / `V1-Y`, production `2009-03`). Likely candidates:
- Internal controller model number
- Bootloader/firmware version string
- Hardware revision code

The string is stable across different data payloads. Not affected by photoresistor (sensor is internal-only for auto-brightness).

## Reset Command

On power-on, the display shows a ~15s boot sequence (FW version, display size) before it renders data.
Sending data immediately after the reset command **skips this boot sequence** entirely.

Discovered via the `ramkareboot` field in the original application's Form1 (dead code — stored but never sent by the original exe).

Sends an immediate power-cycle reset to the display using **address 31** (encoded as `0x7F`):

```
STX + "7F02384A" + ETX
```

| Field | Value | Meaning |
|-------|-------|---------|
| Encoded address | `7F` | addr=31, encoded via `((31 << 2) \| 3) = 0x7F` |
| Command | `02` | Standard command byte |
| Sub-command | `38` | Reset sub-command |
| Checksum | `4A` | `sum(ASCII("7F0238")) % 256 = 0x4A` |

No response from the display. The data renders right away.

Usage:

```bash
python3 etlp_send.py --port /dev/tty.usbmodemXXXX --reboot
```

## Implementation

See `etlp_send.py` in this repository for a working Python implementation.

Usage (flat flags, no subcommands):

```bash
# Send departure data
python3 etlp_send.py --port /dev/tty.usbmodemXXXX \
  --l1 "123" --l2 "WARSZAWA" --l3 "R-7" --l4 "KRAKOW" --wag "001"

# Clear display
python3 etlp_send.py --port /dev/tty.usbmodemXXXX --clear

# Reboot
python3 etlp_send.py --port /dev/tty.usbmodemXXXX --reboot

# Listen for display responses
python3 etlp_send.py --port /dev/tty.usbmodemXXXX --listen

# With serial response readback
python3 etlp_send.py --port /dev/tty.usbmodemXXXX --read \
  --l1 "123" --l2 "WARSZAWA"
```
