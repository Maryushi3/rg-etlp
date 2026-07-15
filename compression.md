# ETLP Display Internal Buffer — Empirical Findings

**Device:** ETLP (132096-07) via USB RS485 (CDC ACM) at `/dev/tty.usbmodem5A7E0300181`, 9600 8N1, address 16

**Last updated:** 2026-07-15

---

## Overview

The display has an internal buffer for scrolling text.  
This buffer stores text in a **compressed form** — the compression is **NOT** run-length encoding.

**Confirmed: RLE is wrong.** ABABAB... compresses identically to AAAA..., and a single interloper in a long run adds zero cost. The algorithm is likely block-based or dictionary-based.

### Empirical facts vs. theoretical models

Most of this document is **empirical**: lengths, ACK presence/absence, and failure zones were measured directly on one display. Explanations like “16-character block,” “binary-tree context,” and “5-bit context depth” are **working hypotheses** that fit the data. They are useful for predicting behavior, but they should not be read as a proven description of the firmware source code.

### Field naming

This document uses logical names **L1–L4** for the four scrolling fields:

| Logical | Wire format | Meaning |
|---------|-------------|---------|
| L1 | `KierL3` | Train number |
| L2 | `KierL4` | Departure station |
| L3 | `KierL5` | Route course |
| L4 | `KierL6` | Destination station |

---

## Key Limits

| Limit | Value | Notes |
|-------|-------|-------|
| Frame size | **1002 bytes** total (STX + body + CRC + ETX) | Body max = **998 bytes** (w/o CRC) |
| Internal scroll buffer | **332 units** | Shared across all four scrolling fields |
| Raw (uncompressed) capacity | **332 characters** | Any unique chars |

The internal buffer stores text in "units" — one unit roughly equals one uncompressed character, but repetitive text uses far fewer units.

---

## Compression Behavior

### Raw mode (no compressible patterns)

When text contains no repeated patterns the display can exploit:
- Each character costs **1 unit**.
- Max text in this mode: **332 chars** (333 fails).

### Compressible patterns

The following patterns compress to the same small size (~16 units for 400 chars):

| Pattern | Raw length | Units used | Ratio |
|---------|-----------|------------|-------|
| 400 × `A` | 400 | ≤ 16 | ≥ 25:1 |
| 400 × `ABAB` (2-char period) | 400 | ≤ 16 | ≥ 25:1 |
| 200 × `A` + 200 × `B` | 400 | ≤ 16 | ≥ 25:1 |
| 400 × `A` + 400 × `B` (one field) | 800 | ~182 | ~4.4:1 |
| 199 × `A` + `B` + 200 × `A` | 400 | ≤ 16 | ≥ 25:1 |
| 800 × `A` | 800 | ~182 | ~4.4:1 |
| 800 × `ABAB` | 800 | ~182 | ~4.4:1 |
| 400 × `ABCABC` (period 3) | 400 | **>332** (fails alone) | — |
| 800 × `ABCABC` | 800 | **>332** (fails alone) | — |
| 400 × `ABCDABCD` (period 4) | 400 | ≤ 16 | ≥ 25:1 |
| 400 × `ABCDEABCDE` (period 5) | 400 | **>332** (fails) | — |
| 400 × `ABCDEFABCDEF` (period 6) | 400 | **>332** (fails) | — |
| 400 × `ABCDEFGH` (period 8) | 400 | ≤ 16 | ≥ 25:1 |
| 400 × random `AB` mix | 400 | **>332** (fails) | — |
| 332 random `AB` mix | 332 | ~332 (raw) | 1:1 |
| 399 × `A` + `B` + 399 × `A` | 799 | ~182 | ~4.4:1 |
| 332 random A–Z | 332 | ~332 | 1:1 |
| 333 random A–Z | 333 | **>332** (fails) | — |

Key observations:
- Compression requires **regular, predictable patterns** — random same-symbol data compresses no better than raw.
- Only **power-of-2 periods** (1, 2, 4, 8, 16, 32) compress; non-power periods (3, 5, 6, 7, 9) are all incompressible.
- This holds regardless of unique symbol count: period 4 with 3 symbols (ABAC) compresses, period 5 with 3 symbols (ABABC) does not.
- A plausible interpretation is a **context-addressed model** where the context is indexed by roughly `k = log2(period)` bits. Non-power periods would leave gaps in the address space, causing a fallback to raw mode. This is one of several possible implementations; the data does not uniquely identify the algorithm.
- The compressor learns **transition patterns** (context-dependent), not just symbol frequencies.
- A single differing character in a long run **costs nothing** extra.
- Alternating two characters (ABAB) compresses **identically** to a single repeated character (AAAA).
- **Three-character period (ABCABC) is NOT compressible** — period 3 is not a power of 2, so the compressor treats it as raw (1 unit/char). Period 4 (ABCDABCD) compresses fine despite having 4 distinct symbols — the constraint is the period, not the symbol count.
- **Not rendering-aware**: space, `0`, `M`, `i` all compress identically at any length. The unit is character-based, not pixel-based.
- **Concatenated runs**: 400A+400B in one field compresses as one 800-char continuous run (~182 units), NOT as two separate runs (16+16=32 units). Compression does not reset at character switches within a field.
- The compression ratio **degrades** with total length across five regimes: raw (R ≤ 332), mini dead zone (333–399), linear (400–716, C = R − 384), buffer dead zone (717–775), and recovery (R ≥ 776, C = R − 618).

### Compression regime constants

The display's compression has **five regimes** for a single repeating character:

| Zone | Range | Compressed units C | Behavior |
|---|---|---|---|
| **Raw** | 1–332 | C = R | 1:1, no compression |
| **Mini dead** | 333–399 | Invalid | C < 16, compressor minimum not met |
| **Linear** | 400–716 | C = R − 384 (min 16) | C(716) = 332 (buffer full) |
| **Buffer dead** | 717–775 | Overflowed | No ACK, data discarded |
| **Recovery** | 776–950 | C = R − 618 | C(776) = 158 ≤ 332 |

Measured data points (single-char runs, padding test):

| R | Max U | C = 332 − U | Binding limit |
|---|---:|---:|---:|
| 400 | 316 | 16 | Buffer |
| 716 | 0 | ~332 | Buffer |
| 717–775 | — | **FAILS** | Dead zone |
| 776 | — | ≤158 | Frame |
| 778 | 172 | ≤160 | Frame |
| 800 | 150 | 182 | Buffer |
| 830 | 120 | 212 | Buffer |
| 850 | 100 | ≤232 | Frame |
| 900 | 50 | ≤282 | Frame |
| 939 | 11 | ≤321 | Frame |

For R ≥ 850, the **serial frame limit** (1002 bytes) becomes the binding constraint — measured compressed values are upper bounds, not exact. The frame body w/o CRC = 48 (overhead) + raw L1 chars + U ≤ 998.

**Constant derivation:**

- **384 = 24 × 16** — the compressor's "free" encoding depth in normal mode. The first 384 bytes of a repetitive run are compressed at effectively zero cost (minimum 16 units per field). Each additional byte beyond 384 costs exactly 1 compressed unit. At R = 716: 716 − 384 = 332, filling the buffer exactly.

- **717** — dead‑zone entry. The linear formula predicts C = 333 > 332, causing **buffer overflow**. This triggers a compressor stall/reset lasting 59 chars (717–775). During the dead zone, the display sends no data ACK and discards data silently. The dead zone boundary is **not char-dependent** (same for A, B, M, 0, space).

- **776** — recovery entry. After the 59-char stall, a recovery compressor activates with a larger free depth of **618** bytes (vs 384). R = 776: 776 − 618 = 158 ≤ 332.

- **618 = 384 + 234**, where 234 is the rebuild penalty after the dead‑zone reset. Neither 234 (14.625 blocks) nor 59 (dead zone length) is an integer multiple of 16 — origin is empirical.

The dead zone **cannot be bypassed** by distributing content across multiple fields — the compressor processes fields sequentially and fails at the first field exceeding 716 chars. It is also **not char-dependent** (identical behavior for A, B, M, 0, space). See [Multi-Field Behavior](#multi-field-behavior).

---

## What the Compression Is NOT

- **Not RLE**: 400×ABAB compresses to same size as 400×A.
- **Not byte-level LZ77**: A single `B` in 798 `A`s adds zero cost (byte-level LZ77 would need a literal or short match).
- **Not fixed-block**: Intruder at positions 0, 1, 7, 8, 15, 16, 31, 32, 63, 64 all cost the same.

Plausible candidate: **16-char block-aligned context model**. The compressor may divide the scroll buffer into **16-character blocks** (one half-row of the 32-char-wide virtual canvas). For compression to engage, the period of the repeated pattern would need to **align with 16-char block boundaries**:

- **Period ≤ 16**: must **divide** 16 (i.e. 1, 2, 4, 8, 16).
- **Period > 16**: must be a **multiple** of 16 (16 × k for k = 1, 2, 3, …).

Every tested case fits this rule:

| Period | Unique symbols | Aligns with 16? | Compresses? |
|--------|---------------|-----------------|-------------|
| 1..8 | any | 16/k = int | ✓ (all) |
| 10, 12, 15 | any | 16/k ≠ int | ✗ (all) |
| 16 | any | 16/16 = 1 | ✓ |
| 17, 24, 33, 36, 40 | any | not k×16 | ✗ (all) |
| 32, 48, 64, 80, 96 | ≤(period width) | k×16 | ✓ (all) |

A 16-char block is a natural fit for LED line-buffer hardware, but the same power-of-2 behavior could also come from a hash table, bitmask, or other power-of-2 data structure. The data rule out many general compressors but do not uniquely identify the implementation.

**Maximum context depth**: The compressor appears to handle at most **~5 bits of distinct context** (32 states). Period 32 works; period 64 with 64 unique symbols fails, but period 64 with only 32 unique symbols works. This suggests the practical limit is on the number of distinct symbols or transitions that must be tracked, not necessarily the raw period length.

---

## Two-Pool Model

The display's scrolling has **two speed groups**, and the internal buffer follows the same split:

| Pool | Rows | Fields | Scroll speed |
|---|---|---|---|
| **Pool A** | Row 1 + Row 3 | L1 + L3 | Faster |
| **Pool B** | Row 2 + Row 4 | L2 + L4 | Slower |

**Each pool is compressed as a single continuous stream** (L1+L3 and L2+L4), NOT per-field. The total 332-unit buffer is shared dynamically between the two pools.

### Pool capacity (compressible period-1 content)

| Scenario | Pool A (L1+L3) | Pool B (L2+L4) | Total raw | Binding limit |
|---|---|---|---|---|
| Pool A only | **716** raw | 0 | 716 | Dead zone ✓ |
| Pool B only | 0 | **608** raw (balanced) | 608 | Buffer |
| Pool B solo (L2 only) | 0 | 332 raw / 400–716 | 332 / 400–716 | Raw gap / Dead zone |
| Both, A=400 | 400+L3≤316 | ≤316 | ≤1032 | Pool B buffer |
| Both, A=619 | 400+219=619 | ≤285 | ≤904 | Pool B buffer |
| Both, A=716 (full) | 400+316=716 | ≤200 | ≤916 | Buffer |
| Both, A=300 | 300+300=600 | ≤304 | ≤908 | Pool B buffer ≈ Pool A |

### Mini dead zone (333–399)

Every field has a **secondary dead zone** at 333–399 raw chars. This is where the linear formula predicts C = R − 384 < 16, but the firmware appears to require a **minimum compressed output of 16 units** (or has no graceful fallback below that threshold):

| Range | Mode | Compressed |
|---|---|---|
| 1–332 | Raw (no compression) | C = R |
| 333–399 | **Mini dead zone** | Fails (C < 16, invalid) |
| 400–716 | Linear compression | C = R − 384 ≥ 16 |

This gap explains why L2 solo at 350 fails but 400 works — and why L2=L4=304 (pool combined = 608 > 384) works: the compressor sees 608 chars in one stream, above the 384 threshold.

### Asymmetric anomalies

When three fields are populated, the order of content matters:
- `400+300+219`: L1=400, L2=300, L3=219 → **fails**
- `400+219+300`: L1=400, L2=219, L3=300 → **works**

Both have identical total raw chars (919) and body size (967). The difference is that L2=300 pushes Pool B's single-field stream into the raw-mode buffer limit (300 < 333, no compression), while L2=219 stays safely in raw mode (219 < 332). The exact mechanism by which Pool A and Pool B share the 332-unit total buffer is non-linear — simple addition of per-pool compressed units does not fully match the observed behavior. These anomalies are likely a firmware edge case.

### Safe operating ranges

| Active pools | Content type | Safe configuration |
|---|---|---|
| Pool A only | Compressible | L1+L3 ≤ 716 |
| Pool B only | Compressible | L2+L4 ≤ 608 (balanced) or L2/L4 in raw (≤332) or linear (≥400, ≤716) |
| Both pools | Compressible | Pool A ≤ 400, Pool B ≤ 300 recommended |
| Any | Unique (random) | 332 chars total across ALL fields |

---

## Open Questions

- **Derivation of 618**: Why 384 + 234? Neither component is a multiple of 16. Likely a firmware constant, not derivable from the protocol alone.
- **Exact two-pool allocation curve**: Pool B capacity vs Pool A load is non-linear. More data points would tighten the empirical curve, but the formula is likely firmware-internal.
- **Model uniqueness**: The 16-character block and 5-bit context are hypotheses. Other power-of-2 structures (hash tables, bitmasks, state machines) could produce the same period-dependent behavior. Without firmware source, the exact algorithm remains unknown.
- **Firmware version variance**: All constants (384, 618, 332, dead zone boundaries) were measured on one unit. Unknown if they hold across firmware revisions or production batches.

---

## Measurement Methodology

1. Send L1 = test string, L2 = padding (`U` chars), L3/L4 = empty (in the data packet body).
2. Binary search `U` to find max that displays successfully.
3. Compressed units = 332 − max_U (when buffer is the limit) or computed from frame size (when frame is the limit).

### Automated pass/fail detection

The display sends a **data received ACK** (`FF 02 30 33 30 32 33 42 33 41 03`, hex body `03023B3A`) approximately 0.8 s after the **data packet** frame, but **only when the compressed data fits in the internal buffer**. When the data overflows the buffer, this ACK is **absent** — the display silently discards the data but continues the protocol sequence normally.

This allows programmatic binary-search automation: after sending the data packet, wait 1 s, then check for the presence of `03023B3A` in the serial response. No visual inspection required.

The methodology is implemented in the `_send_and_check` pattern — send data packet, wait 1.5 s, read serial response, check for ACK.

The two limits are:
- **Internal buffer**: 332 units (determined by 332 random chars working, 333 failing).
- **Frame size**: 1002 bytes serial (determined by frame ≤ 1002 working, 1003 failing).
