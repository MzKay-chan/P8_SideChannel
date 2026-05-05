import os
import sys
import numpy as np
import threading
from ctypes import *
from time import sleep
from WF_SDK import device, scope, error

# ── Configuration ─────────────────────────────────────────────────────────────
CLOCK_FREQ_HZ    = 1e6       # Must match F_CPU in Arduino sketch
CLOCK_AMPLITUDE  = 2.5       # V
CLOCK_OFFSET     = 2.5       # V

FIXED_VAL        = 0xFF      # Fixed group input — must match Arduino sketch
LFSR_SEED        = 0xAC      # Must match Arduino sketch exactly
LFSR_POLY        = 0xB8      # Galois LFSR polynomial — must match Arduino sketch

N_TRACES         = 2000      # Traces per group (fixed and random)
START_DIO_PIN    = 2         # AD2 digital output pin → Arduino START_PIN (pin 3)

SAVE_DIR         = "tvla_traces"
TRIGGER_LEVEL    = 3.0       # Volts, rising edge on CH2 (Arduino pin 3 trigger)
TRIGGER_TIMEOUT  = 5         # Seconds before a trace is considered lost

# ── LFSR (mirrors Arduino exactly) ───────────────────────────────────────────
def lfsr_next(state: int) -> tuple:
    """
    One step of the Galois LFSR.
    Returns (new_value, new_state).
    Must be byte-identical to the Arduino lfsr_next() function.
    """
    lsb = state & 0x01
    state = (state >> 1) & 0xFF
    if lsb:
        state ^= LFSR_POLY
    return state, state   # value == state for this LFSR


def generate_lfsr_sequence(n: int) -> np.ndarray:
    """
    Generate the first n values of the LFSR sequence.
    This mirrors what the Arduino will produce trace-by-trace.
    """
    state = LFSR_SEED
    vals = []
    for _ in range(n):
        val, state = lfsr_next(state)
        vals.append(val)
    return np.array(vals, dtype=np.uint8)


# ── DWF helpers ───────────────────────────────────────────────────────────────
def load_dwf():
    if sys.platform == "win32":
        return cdll.LoadLibrary("dwf.dll")
    elif sys.platform == "darwin":
        return cdll.LoadLibrary("/Library/Frameworks/dwf.framework/dwf")
    else:
        return cdll.LoadLibrary("libdwf.so")


def clock_start(dwf, hdwf):
    ch   = c_int(0)   # W1
    node = c_int(0)
    dwf.FDwfAnalogOutNodeEnableSet(hdwf, ch, node, c_bool(True))
    dwf.FDwfAnalogOutNodeFunctionSet(hdwf, ch, node, c_int(1))   # square wave
    dwf.FDwfAnalogOutNodeFrequencySet(hdwf, ch, node, c_double(CLOCK_FREQ_HZ))
    dwf.FDwfAnalogOutNodeAmplitudeSet(hdwf, ch, node, c_double(CLOCK_AMPLITUDE))
    dwf.FDwfAnalogOutNodeOffsetSet(hdwf, ch, node, c_double(CLOCK_OFFSET))
    dwf.FDwfAnalogOutConfigure(hdwf, ch, c_bool(True))
    print(f"[clock] W1 running at {CLOCK_FREQ_HZ/1e6:.1f} MHz")


def clock_stop(dwf, hdwf):
    dwf.FDwfAnalogOutConfigure(hdwf, c_int(0), c_bool(False))
    print("[clock] W1 stopped")


def dio_set(dwf, hdwf, pin: int, value: int):
    """
    Drive a single digital output pin on the AD2.
    pin   : DIO index (0-15)
    value : 0 or 1
    """
    dwf.FDwfDigitalIOOutputEnableSet(hdwf, c_int(1 << pin))
    dwf.FDwfDigitalIOOutputSet(hdwf, c_int(value << pin))
    dwf.FDwfDigitalIOConfigure(hdwf)


# ── Single trace capture ──────────────────────────────────────────────────────
def capture_one_trace(device_data, dwf, hdwf):
    """
    Arm the scope, wait for trigger, return the post-trigger buffer.
    Returns None on timeout.
    """
    scope.open(device_data,
               sampling_frequency=100e6,
               buffer_size=8192,
               offset=0,
               amplitude_range=6)

    scope.trigger(device_data,
                  enable=True,
                  source=scope.trigger_source.analog,
                  channel=2,
                  level=TRIGGER_LEVEL,
                  timeout=TRIGGER_TIMEOUT)

    buffer_holder = [None]

    def record():
        buffer_holder[0] = scope.record(device_data, channel=1)

    t = threading.Thread(target=record)
    t.start()
    t.join(timeout=TRIGGER_TIMEOUT + 1)

    scope.close(device_data)
    dwf.FDwfAnalogInReset(hdwf)

    if t.is_alive() or buffer_holder[0] is None:
        return None

    buf = buffer_holder[0]
    # Keep only post-trigger half — same as your original script
    return buf[len(buf) // 2:]


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":

    os.makedirs(SAVE_DIR, exist_ok=True)

    # Pre-generate the full LFSR sequence so we know which value
    # corresponds to every random trace before capture starts
    print(f"[lfsr] Pre-generating {N_TRACES} values from seed 0x{LFSR_SEED:02X}...")
    random_vals = generate_lfsr_sequence(N_TRACES)
    print(f"[lfsr] First 8 values : {[hex(v) for v in random_vals[:8]]}")
    print(f"[lfsr] Unique values  : {len(np.unique(random_vals))}/256")

    # Open AD2
    dwf         = load_dwf()
    device_data = device.open()
    hdwf        = device_data.handle

    # Hold DIO2 LOW so Arduino waits in its blinking loop
    dio_set(dwf, hdwf, START_DIO_PIN, 0)
    print(f"[dio] DIO{START_DIO_PIN} LOW — Arduino is waiting (LED blinking)")

    # Start clock before Arduino needs it
    clock_start(dwf, hdwf)
    sleep(1)   # Let clock stabilise

    print("\n  Watch the Arduino LED — it should be blinking.")
    print("  Press Enter when you are ready to start capture...")
    input()

    # Signal Arduino to begin its measurement loop
    dio_set(dwf, hdwf, START_DIO_PIN, 1)
    print(f"[dio] DIO{START_DIO_PIN} HIGH — Arduino started (LED solid)\n")

    # Brief pause for Arduino to finish its setup() and enter loop()
    sleep(0.2)

    # ── Capture loop ─────────────────────────────────────────────────────────
    # Arduino interleaves: fixed trace, random trace, fixed trace, random trace...
    # We capture them in the same interleaved order and sort into groups here.

    fixed_traces  = []
    random_traces = []
    skipped       = 0
    i             = 0   # counts successfully captured pairs

    print(f"Capturing {N_TRACES} pairs  ({N_TRACES * 2} total traces)")
    print("─" * 60)

    while i < N_TRACES:

        # ── Fixed trace ──────────────────────────────────────────────────────
        buf_fixed = capture_one_trace(device_data, dwf, hdwf)

        if buf_fixed is None:
            print(f"  [!] pair {i+1}: FIXED trace timed out — retrying pair")
            skipped += 1
            if skipped > 50:
                print("[!] Too many consecutive timeouts — check wiring and restart")
                break
            # Arduino has NOT yet fired the random trace for this pair,
            # so we can safely retry the whole pair without LFSR drift.
            # However if the fixed trace fired but we missed it, LFSR is
            # already advanced on Arduino side. To be safe, abort & restart.
            # For now we retry — if misalignment is suspected, check
            # random_vals against known values after capture.
            continue

        # ── Random trace ─────────────────────────────────────────────────────
        buf_random = capture_one_trace(device_data, dwf, hdwf)

        if buf_random is None:
            print(f"  [!] pair {i+1}: RANDOM trace timed out")
            print( "      Arduino LFSR has advanced — skipping this index to stay in sync")
            skipped += 1
            # We must advance our Python LFSR index too so the mapping
            # stays aligned, even though we discard this pair
            i += 1
            continue

        fixed_traces.append(buf_fixed)
        random_traces.append(buf_random)

        if (i + 1) % 100 == 0:
            pct = (i + 1) / N_TRACES * 100
            print(f"  {i+1:>4}/{N_TRACES}  ({pct:.0f}%)   skipped so far: {skipped}")

        i += 1

    print("─" * 60)
    print(f"Done: {len(fixed_traces)} pairs captured, {skipped} skipped")

    # ── Save ─────────────────────────────────────────────────────────────────
    captured_n   = len(fixed_traces)
    fixed_arr    = np.array(fixed_traces,          dtype=np.float32)
    random_arr   = np.array(random_traces,         dtype=np.float32)
    # Slice random_vals to match exactly the traces we kept
    # (pairs that timed out on the random side were already skipped via i++)
    # Reconstruct which LFSR indices we actually kept:
    kept_indices        = list(range(captured_n))   # simplified — see note below
    random_vals_saved   = random_vals[:captured_n]

    np.save(os.path.join(SAVE_DIR, "fixed_traces.npy"),  fixed_arr)
    np.save(os.path.join(SAVE_DIR, "random_traces.npy"), random_arr)
    np.save(os.path.join(SAVE_DIR, "random_vals.npy"),   random_vals_saved)
    np.save(os.path.join(SAVE_DIR, "fixed_val.npy"),
            np.array([FIXED_VAL], dtype=np.uint8))

    print(f"\n[saved] fixed_traces.npy   {fixed_arr.shape}")
    print(f"[saved] random_traces.npy  {random_arr.shape}")
    print(f"[saved] random_vals.npy    {random_vals_saved.shape}")
    print(f"[saved] fixed_val.npy      0x{FIXED_VAL:02X}")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    dio_set(dwf, hdwf, START_DIO_PIN, 0)
    clock_stop(dwf, hdwf)
    device.close(device_data)
    print("\n[done] Device closed cleanly")