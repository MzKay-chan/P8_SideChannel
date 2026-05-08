import os
import sys
import numpy as np
import threading
from ctypes import *
from time import sleep
from WF_SDK import device, scope, error

# ── Configuration ─────────────────────────────────────────────────────────────
CLOCK_FREQ_HZ    = 16e6       # Must match F_CPU in Arduino sketch
CLOCK_AMPLITUDE  = 2.5       # V
CLOCK_OFFSET     = 2.5       # V

FIXED_VAL        = 0xFF      # Fixed group input — must match Arduino sketch

# ── TEST_NAME must match the TEST_VARIANT compiled into the Arduino sketch ───
# Update this string whenever you reflash a new variant.
# Captured traces go into tvla_traces_<TEST_NAME>/  so each instruction's
# dataset is preserved separately and easy to compare later.
TEST_NAME        = "eor-HW"

N_TRACES         = 2048      # Traces per group — must match Arduino sketch (multiple of 256)
HANDSHAKE_DIO_PIN = 2        # AD2 DIO → Arduino HANDSHAKE_PIN (pin 2): start signal + per-trace ACK

SAVE_DIR         = f"tvla_traces_{TEST_NAME}"

# ── Scope acquisition parameters ─────────────────────────────────────────────
SAMPLING_FREQ_HZ = 100e6     # 100 MS/s
BUFFER_SIZE      = 2048      # samples per capture (~20 µs window — covers asm + slack)
AMPLITUDE_RANGE  = 6         # V
TRIGGER_LEVEL    = 3.0       # V, rising edge on CH2 (Arduino pin 3 trigger)
TRIGGER_TIMEOUT  = 0.2       # Seconds the scope itself waits for trigger before giving up
                              # (handshake fires trigger within ~100 µs; >50 ms means something's broken)

CAPTURE_TIME_S   = BUFFER_SIZE / SAMPLING_FREQ_HZ            # ~82 µs at 8192 / 100 MS/s
USB_READBACK_S   = 0.2                                        # generous slack for buffer transfer
JOIN_TIMEOUT_S   = TRIGGER_TIMEOUT + CAPTURE_TIME_S + USB_READBACK_S

# ── Random-value sequence (mirrors Arduino exactly) ──────────────────────────
def generate_random_sequence(n: int) -> np.ndarray:
    """
    Mirror the Arduino: val = i & 0xFF for i in [0, n).
    Each byte value 0..255 appears n/256 times when n is a multiple of 256.
    """
    return (np.arange(n, dtype=np.uint32) & 0xFF).astype(np.uint8)


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


# Cache of OE/value masks so per-pin updates don't clobber other pins
_dio_oe_mask  = 0
_dio_val_mask = 0

def dio_init(dwf, hdwf, output_pins: list):
    """Enable a set of DIO pins as outputs and drive them all LOW."""
    global _dio_oe_mask, _dio_val_mask
    _dio_oe_mask  = 0
    for p in output_pins:
        _dio_oe_mask |= (1 << p)
    _dio_val_mask = 0
    dwf.FDwfDigitalIOOutputEnableSet(hdwf, c_int(_dio_oe_mask))
    dwf.FDwfDigitalIOOutputSet(hdwf, c_int(_dio_val_mask))
    dwf.FDwfDigitalIOConfigure(hdwf)


def dio_set(dwf, hdwf, pin: int, value: int):
    """Update one bit of the cached DIO output value without touching others."""
    global _dio_val_mask
    if value:
        _dio_val_mask |=  (1 << pin)
    else:
        _dio_val_mask &= ~(1 << pin)
    dwf.FDwfDigitalIOOutputSet(hdwf, c_int(_dio_val_mask))
    dwf.FDwfDigitalIOConfigure(hdwf)


# ── Single trace capture ──────────────────────────────────────────────────────
def capture_one_trace(device_data, dwf, hdwf):
    """
    Arm the scope, wait for trigger, return the post-trigger buffer.
    Returns None on timeout.
    """
    scope.open(device_data,
               sampling_frequency=SAMPLING_FREQ_HZ,
               buffer_size=BUFFER_SIZE,
               offset=0,
               amplitude_range=AMPLITUDE_RANGE)

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

    # Scope is armed and the record thread is waiting — release the Arduino
    dio_set(dwf, hdwf, HANDSHAKE_DIO_PIN, 1)

    t.join(timeout=JOIN_TIMEOUT_S)

    # Drop the line so the Arduino completes its post-trigger wait_hs_low()
    dio_set(dwf, hdwf, HANDSHAKE_DIO_PIN, 0)

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

    # Pre-generate the deterministic random-value sequence the Arduino will use
    print(f"[seq] Pre-generating {N_TRACES} values (val = i & 0xFF)...")
    random_vals = generate_random_sequence(N_TRACES)
    print(f"[seq] First 8 values : {[hex(v) for v in random_vals[:8]]}")
    print(f"[seq] Unique values  : {len(np.unique(random_vals))}/256")
    print(f"[seq] Per-value count: {N_TRACES // 256}  (remainder {N_TRACES % 256})")

    # Open AD2
    dwf         = load_dwf()
    device_data = device.open()
    hdwf        = device_data.handle

    # Enable HANDSHAKE pin as output, driven LOW
    dio_init(dwf, hdwf, [HANDSHAKE_DIO_PIN])
    print(f"[dio] DIO{HANDSHAKE_DIO_PIN}=HANDSHAKE LOW — Arduino is waiting (LED blinking)")

    # Start clock before Arduino needs it
    clock_start(dwf, hdwf)
    sleep(1)   # Let clock stabilise

    print("\n  Watch the Arduino LED — it should be blinking.")
    print("  Press Enter when you are ready to start capture...")
    input()

    # Pulse the handshake line HIGH then LOW: the rising edge releases setup()'s
    # blink loop, the falling edge satisfies its wait_hs_low() so loop() begins
    # from a known-LOW state, ready for the per-trace handshake.
    dio_set(dwf, hdwf, HANDSHAKE_DIO_PIN, 1)
    sleep(0.05)
    dio_set(dwf, hdwf, HANDSHAKE_DIO_PIN, 0)
    print(f"[dio] DIO{HANDSHAKE_DIO_PIN} pulsed — Arduino started (LED solid)\n")

    # Brief pause for Arduino to finish its setup() and enter loop()
    sleep(0.2)

    # ── Capture loop ─────────────────────────────────────────────────────────
    # Arduino interleaves: fixed trace, random trace, fixed trace, random trace...
    # We capture them in the same interleaved order and sort into groups here.

    fixed_traces  = []
    random_traces = []
    kept_indices  = []  # Arduino-side i values for each captured pair
    skipped       = 0
    i             = 0   # tracks Arduino's pair counter (not just successes)

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
            # so we can safely retry without the random-value index drifting.
            # If the fixed trace actually fired but we missed it, the Arduino
            # counter is already advanced — abort & restart in that case.
            continue

        # ── Random trace ─────────────────────────────────────────────────────
        buf_random = capture_one_trace(device_data, dwf, hdwf)

        if buf_random is None:
            print(f"  [!] pair {i+1}: RANDOM trace timed out")
            print( "      Arduino counter has advanced — skipping this index to stay in sync")
            skipped += 1
            # Advance Python's index too so the value mapping stays aligned
            i += 1
            continue

        fixed_traces.append(buf_fixed)
        random_traces.append(buf_random)
        kept_indices.append(i)

        if (i + 1) % 100 == 0:
            pct = (i + 1) / N_TRACES * 100
            print(f"  {i+1:>4}/{N_TRACES}  ({pct:.0f}%)   skipped so far: {skipped}")

        i += 1
    # Mirror the Arduino's hw table on the Python side
    hw_bytes = [[] for _ in range(9)]
    for b in range(256):
        hw = bin(b).count('1')
        hw_bytes[hw].append(b)

    traces_per_hw = N_TRACES // 9
    hw_index = [0] * 9

    random_vals = []
    for i in range(N_TRACES):
        hw = i // traces_per_hw
        if hw > 8:
            hw = 8
        val = hw_bytes[hw][hw_index[hw] % len(hw_bytes[hw])]
        hw_index[hw] += 1
        random_vals.append(val)

    random_vals = np.array(random_vals, dtype=np.uint8)
    print("─" * 60)
    print(f"Done: {len(fixed_traces)} pairs captured, {skipped} skipped")

    # ── Save ─────────────────────────────────────────────────────────────────
    captured_n   = len(fixed_traces)
    fixed_arr    = np.array(fixed_traces,          dtype=np.float32)
    random_arr   = np.array(random_traces,         dtype=np.float32)
    random_vals_saved   = random_vals[np.array(kept_indices, dtype=np.int64)]

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
    dio_set(dwf, hdwf, HANDSHAKE_DIO_PIN, 0)
    clock_stop(dwf, hdwf)
    device.close(device_data)
    print("\n[done] Device closed cleanly")