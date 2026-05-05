# Side-channel pipeline changes — 2026-05-05 / 2026-05-06

This is a hand-off note for the rest of the team explaining what changed in
the capture / analysis pipeline this session, and why.

The original `tvla_analysis.py` is **untouched** so the other person's work
isn't disturbed. The new analysis lives in `tvla_analysis.backup.py` (yes,
the name is misleading — it's the *new* version, with all fixes applied).

The Arduino sketch (`Arduino_sketchs/sketch_assembly/sketch_assembly.ino`)
and `tvla.py` were both modified directly because they have to stay in sync
with each other and with the new analysis.


## TL;DR — what changed and why

1. **Replaced LFSR random bytes with a deterministic round-robin sequence.**
   Each byte value 0..255 now appears exactly `N_TRACES/256` times. This kills
   the wildly imbalanced HW groups we had under the LFSR (HW=8 had only 8
   traces, HW=4 had 547).

2. **Added a software handshake** between Python and Arduino over the
   existing DIO 2 / pin 2 wire. Python only releases the Arduino to fire a
   trigger after the scope is armed, eliminating missed traces.

3. **Replaced `digitalWrite(TRIGGER_PIN, ...)` with direct port writes
   (`sbi` / `cbi`).** At F_CPU = 1 MHz, `digitalWrite` was ~60 cycles per
   call (≈60 µs). Direct port writes are 1 cycle. This is the single biggest
   improvement — previously ~80% of every trace was `digitalWrite` overhead
   instead of the asm we wanted to measure.

4. **`cli` / `sei` around the asm.** Stops Timer0's millis ISR from
   pre-empting `run_test()` and shifting it relative to the trigger.
   Removes inter-trace jitter that was smearing leakage across many sample
   positions.

5. **Made `run_test` `always_inline`.** No CALL/RET overhead between
   handshake polling and the trigger edge.

6. **Built a 12-variant test menu in the sketch** (TEST_VARIANT preprocessor
   selector). Lets us characterise leakage per-instruction so we can later
   pick low-leakage building blocks for the constant-time strcmp.

7. **Rewrote the analysis to be multi-test aware.** Auto-discovers every
   `tvla_traces_<name>/` folder it finds, runs the full pipeline on each,
   produces a cross-test comparison bar chart and a summary.json table.

8. **Fixed several real calculation bugs in the analysis** (alignment used
   per-trace thresholds, variance was biased, cycle indexing assumed
   trigger = cycle 0, plot 1 hardcoded a 10 µs xlim, HW correlation was a
   slow per-sample loop). Details below.


## Arduino sketch — `sketch_assembly.ino`

### Why `i & 0xFF` instead of an LFSR

The LFSR seeded at 0xAC happens to skip 0x00 entirely (Galois LFSR with
state 0 is absorbing) and produced highly skewed counts per byte. Captures
of 2000 traces gave only 8 traces with HW=8 and 547 with HW=4 — useless for
SNR / per-value statistics.

`val = (uint8_t)(i & 0xFF)` walks 0..255 round-robin, so with N_TRACES = 2048
every value appears exactly 8 times. Python mirrors this in
`generate_random_sequence()` — same identity in both languages, no
synchronization to maintain.

### Why the handshake (HANDSHAKE_PIN, dual-purpose)

Previously the Arduino was free-running and Python tried to keep up by
re-arming the scope between traces. Anything > the worst-case re-arm time
(usually USB-bound, sometimes 30+ ms) caused a missed trigger. With 2048
pairs that's a near-certainty of misalignment.

The handshake reuses the existing START line (DIO 2 → pin 2). Same wire,
no new connection. Semantics:

- `setup()`: blink while LOW (waiting), exit blink when HIGH, then `wait_hs_low()`
  so `loop()` starts from a known-LOW state
- Per trace: `wait_hs_high()` → fire trigger → `wait_hs_low()` → settle delay

Python pulses HIGH→LOW after Enter to release setup, then HIGH-during-arm /
LOW-after-capture per trace. A trace cannot be missed.

### Why direct port writes (sbi/cbi) for the trigger

Stock `digitalWrite()` looks up `digital_pin_to_port_PGM`, masks/restores
SREG, calls `turnOffPWM`, etc. It's ~60 instructions. At F_CPU = 1 MHz that
costs ~60 µs PER CALL. Two calls per trace (HIGH then LOW) eats ~120 µs —
longer than the entire 80 µs scope window we were capturing.

That meant the scope was triggering inside `digitalWrite` and seeing
mostly more `digitalWrite` plus a thin slice of `run_test`. The TVLA
"no leakage detected" result wasn't telling us the asm doesn't leak — it
was telling us we were measuring `digitalWrite`.

`sbi` and `cbi` are 1-cycle (1 µs) AVR instructions. Now the trigger goes
HIGH, the asm runs, and the trigger goes LOW all within ~5 µs — the asm is
~50 % of the captured window instead of ~8 %.

### Why `cli` / `sei` around the asm

Default Arduino setup leaves Timer0 running for `millis()`. At F_CPU = 1 MHz
that ISR fires roughly every 16 ms. The asm window is 5 µs, so collision
probability per trace is ~0.03 % — small but non-zero, and when it happens
it shifts the asm by 4-5 cycles, smearing any leak over multiple sample
positions and diluting |t|.

`cli` / `sei` add 1 cycle each to either side of the trigger window. Cheap,
and removes the smear entirely.

Side effect: `millis()` falls behind by `N_TRACES * 2 * DELAY_US ≈ 2 s`
over a full capture run. We don't use it, so it doesn't matter — flagged
in case future code does.

### Why the `TEST_VARIANT` menu

To build a leakiness map across instructions we need to run TVLA on each
instruction in isolation. The menu uses preprocessor selection so:

- `OP_ASM` is exactly the instruction(s) being measured (between sbi/cbi)
- `PRE_ASM` is setup that runs *before* the trigger (loading r16 with a
  fixed comparand for `cp`/`cpse`, pre-storing a byte to SRAM for `lds`,
  etc.) — not measured
- Each test compiles down to a known-cycle-count atomic block

Variants 0–11 cover: nop (control), mov, eor, and, or, add, sub, cp, cpse,
sts, lds, mul. Easy to add more (swap, com, neg, lsl, lsr, inc, dec,
ror, etc.) — copy any existing variant and change the asm + name.


## `tvla.py`

### Single source of truth — `TEST_NAME`

A `TEST_NAME` constant at the top of `tvla.py` controls `SAVE_DIR =
"tvla_traces_<name>"`. Update it whenever you flash a new TEST_VARIANT
in the sketch — this is how datasets stay separated by instruction.

### `dio_init` + cached OE/value masks

The previous `dio_set()` called `FDwfDigitalIOOutputEnableSet(hdwf, 1<<pin)`
on every call, which OVERWRITES the entire 16-bit OE register. With only
one DIO pin in use it was fine, but it would silently break the moment a
second output pin was added (it would drop the first one back to high-Z).

`dio_init([pins])` now sets the OE mask once at startup, and `dio_set()`
only flips one bit of a cached value mask without touching OE. Future-proof
for adding more output pins (status LED, second trigger, etc.) without
rewiring the function.

### Bug fix: `random_vals` indexed by `kept_indices`

When a random-side trace timed out, the old code did `i += 1; continue`
but then saved `random_vals[:captured_n]` — which is the WRONG values for
the actual traces kept. Now we track `kept_indices` (the Arduino-side `i`
of each successfully captured pair) and save `random_vals[kept_indices]`.
Note: with the handshake in place, timeouts should never happen, but the
fix is correct anyway.

### Capture timeouts derived from real numbers

Old: `t.join(timeout=TRIGGER_TIMEOUT + 1)`. The "+1" was a magic number.

New:
```
CAPTURE_TIME_S = BUFFER_SIZE / SAMPLING_FREQ_HZ
JOIN_TIMEOUT_S = TRIGGER_TIMEOUT + CAPTURE_TIME_S + USB_READBACK_S
```

`TRIGGER_TIMEOUT` itself dropped from 5 s → 0.2 s — with the handshake the
trigger fires within ~100 µs of ACK going HIGH. 0.2 s means we surface
hardware-broken failures ~25× faster than before.

### `BUFFER_SIZE` 8192 → 2048

The old 80 µs window was overkill for a 5-cycle asm block. 2048 samples =
20 µs window covers the whole asm + slack and gives the analysis 2× the
sample density per useful cycle.


## `tvla_analysis.backup.py`

This is the *new* analysis. The original `tvla_analysis.py` is unchanged so
the other person's parallel work continues uninterrupted. Datasets and
plots get separate folders so both analyses can run on the same data.

### Multi-test orchestration

Three usage modes:

```
python .\tvla_analysis.backup.py                     # process every  tvla_traces_*/  found
python .\tvla_analysis.backup.py mov                 # one test
python .\tvla_analysis.backup.py mov eor and add     # several specific tests
```

Auto-discovery means you don't need data for all 12 variants to run it —
it just processes whatever's there.

Outputs:

- `tvla_plots_<name>/` per test — the six plots that already existed
  (mean traces, t-stat, SNR, HW correlation, HW scatter, HW overlay)
- `tvla_summary/comparison.png` — a 2×2 bar chart of peak |t|, peak SNR,
  peak |HW r|, R² across every test analysed, sorted least → most leaky.
  Bars are red above the TVLA threshold, green below.
- `tvla_summary/summary.json` — same numbers as a machine-readable table

Toggle `SHOW_PLOTS = True` at the top to make plots pop up interactively
(blocks until you close each). Default `False` for batch friendliness.

### Calculation bugs that were fixed

1. **`align_traces` used a per-trace midpoint threshold.** Different traces
   crossed the threshold at different absolute voltages, so the alignment
   landed on different features (sometimes a clock edge, sometimes a
   signal transition, sometimes noise). Now uses a single global threshold
   = median of all per-trace midpoints in the search window, so every
   trace aligns to the same feature.

   Also added an `ALIGN_SEARCH_WINDOW = 0` escape hatch to skip realignment
   entirely — the scope's hardware trigger is already sample-accurate, so
   software realignment can hurt more than it helps.

2. **`compute_snr` used population variance (`np.var` default ddof=0)**
   instead of sample variance (`ddof=1`). At small group sizes this biases
   SNR downward. Now uses `ddof=1` throughout.

3. **`compute_snr` silently dropped single-sample groups.** Now prints a
   warning when this happens so you know how many groups got skipped.

4. **`leaky_cycles = leaky_samples // SAMPLES_PER_CYCLE` assumed sample 0
   = first cycle of `run_test`.** It isn't — there's a fixed offset
   between the trigger edge and the start of `OP_ASM`. With direct port
   writes that offset is 1 cycle (sbi takes 1 cycle before OP_ASM runs),
   so `CYCLE_OFFSET_SAMPLES = 100`. All cycle-index reports
   (leaky cycles, peak SNR cycle, peak HW cycle, plot gridlines) now
   subtract this offset, so "cycle N" really means "the Nth cycle of
   `run_test`'s OP_ASM" instead of "the Nth cycle since the trigger".

5. **HW correlation was a per-sample Python loop (`np.corrcoef` × N
   samples).** Now vectorised — same math, ~100× faster on 2000+ samples.

6. **Plot 1 had `ax.set_xlim(0, 10)`** hardcoded, cutting off ~80 % of
   the trace. Now uses `[t_axis[0], t_axis[-1]]` to show the whole window.

7. **`hw_vals = [bin(v).count('1') for v in random_vals]`** was a Python
   loop. Replaced with `np.unpackbits(...).sum(axis=1)` — vectorised.


## New end-to-end workflow

For each instruction you want to characterise:

1. In `sketch_assembly.ino`, set `#define TEST_VARIANT N` (see menu in the
   file). Compile and flash.
2. In `tvla.py`, set `TEST_NAME = "<name>"` to match (e.g. "mov", "eor").
3. Run `python .\tvla.py` — capture writes traces to
   `tvla_traces_<name>/`.
4. Repeat steps 1-3 for as many variants as you want.
5. Once: `python .\tvla_analysis.backup.py` — produces per-test plots and
   a cross-test comparison.

You don't have to capture all 12 in one sitting. The analysis picks up
whatever datasets are present, so you can capture mov today, eor tomorrow,
and re-run the analysis at any point to see the comparison so far.


## Expected impact on results

Before these changes (`tvla_analysis.py`, `tvla_traces/`, old data):
- N = 2000, 4096 samples (40 µs window), LFSR-skewed groups
- Peak |t| ≈ 0.5 (well below 4.5 threshold)
- Peak SNR ≈ 0.16, peak |HW r| ≈ 0.05, R² ≈ 0.0025
- Plots show clean clock-cycle structure across all 40 µs — but ~92 % of
  that is `digitalWrite` overhead, not the asm. Conclusion: chain works,
  but we were measuring the wrong thing.

Predicted after these changes (next capture):
- The asm window will occupy ~50 % of each trace instead of ~8 %, so the
  effective SNR per trace is ~6× higher. That's equivalent to ~36× more
  traces under the old setup.
- For a deliberately leaky instruction (mul, sts, lds), expect peak |t|
  in the tens. For a baseline (nop), expect peak |t| ≈ 0–1 (noise floor).
- For mov / eor / and / or / cp / cpse, expect somewhere in between —
  that's the actual research output we want.

If `nop` still shows |t| > 4.5 something is broken upstream — that's the
sanity check.


## Files touched

- `Arduino_sketchs/sketch_assembly/sketch_assembly.ino` — full rewrite
- `tvla.py` — modified in place
- `tvla_analysis.py` — UNTOUCHED (other person is working on this)
- `tvla_analysis.backup.py` — full rewrite (multi-test analyser)
- `CHANGES.md` — this file
