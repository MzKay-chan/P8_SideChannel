"""
collect_hw_traces_v3.py
────────────────────────────────────────────────────────────────────────────
Scope open/close happens inside the capture loop — matching the pattern
from attack_clockv2.py that you know works.

Change TARGET_BYTE and run once per pattern:
  0x00  HW=0   (minimum power)
  0xFF  HW=8   (maximum power)
  0xAA  HW=4   (medium)
  0x0F  HW=4   (same HW as 0xAA — should look identical)
────────────────────────────────────────────────────────────────────────────
"""

from WF_SDK import device, scope, error
from ctypes import *
import numpy as np
import matplotlib.pyplot as plt
import os
from time import sleep

# ── Configuration ─────────────────────────────────────────────────────────────

TARGET_BYTE  = 0xFF     # ← change this per run
NUM_TRACES   = 100

CLOCK_FREQ_HZ   = 16e6  # 1 MHz — 100 samples/cycle at 100 MS/s
CLOCK_AMPLITUDE = 2.5
CLOCK_OFFSET    = 2.5

SAMPLE_RATE  = 100e6
BUFFER_SIZE  = 4096     # ~40 µs window at 100 MS/s

# Match what WaveForms showed: signal at ~4.5 V, swing ~200 mV
# CH1 offset = -4.445 V centres the signal, range = 0.5 V captures the swing
SCOPE_OFFSET     = -4.445   # V
SCOPE_RANGE      =  2    # V  (±0.5 V around offset)

TRIGGER_CHANNEL  = 2        # CH2 = PB0 from ATmega
TRIGGER_LEVEL    = 2.15     # V rising edge — matches your WaveForms setting
TRIGGER_TIMEOUT  = 6        # seconds

INTER_TRACE_DELAY = 0.05    # seconds between traces — gives scope time to re-arm
                             # increase to 0.05 if you still get stale traces

OUTPUT_DIR = 'traces_hw'

# ── Clock ──────────────────────────────────────────────────────────────────────

def load_dwf():
    import sys
    if sys.platform == "win32":
        return cdll.LoadLibrary("dwf.dll")
    elif sys.platform == "darwin":
        return cdll.LoadLibrary("/Library/Frameworks/dwf.framework/dwf")
    else:
        return cdll.LoadLibrary("libdwf.so")

def clock_start(dwf, hdwf):
    ch = c_int(0); node = c_int(0)
    dwf.FDwfAnalogOutNodeEnableSet(hdwf, ch, node, c_bool(True))
    dwf.FDwfAnalogOutNodeFunctionSet(hdwf, ch, node, c_int(1))
    dwf.FDwfAnalogOutNodeFrequencySet(hdwf, ch, node, c_double(CLOCK_FREQ_HZ))
    dwf.FDwfAnalogOutNodeAmplitudeSet(hdwf, ch, node, c_double(CLOCK_AMPLITUDE))
    dwf.FDwfAnalogOutNodeOffsetSet(hdwf, ch, node, c_double(CLOCK_OFFSET))
    dwf.FDwfAnalogOutConfigure(hdwf, ch, c_bool(True))
    print(f"[clock] W1 at {CLOCK_FREQ_HZ/1e6:.2f} MHz")

def clock_stop(dwf, hdwf):
    dwf.FDwfAnalogOutConfigure(hdwf, c_int(0), c_bool(False))
    print("[clock] stopped")

# ── Capture loop ───────────────────────────────────────────────────────────────

def collect_traces(device_data, num_traces, dwf, hdwf):
    traces = []
    failed = 0

    for i in range(num_traces):

        # Open scope fresh for each trace — this is what resets and re-arms
        scope.open(device_data,
                   sampling_frequency=SAMPLE_RATE,
                   buffer_size=BUFFER_SIZE,
                   offset=SCOPE_OFFSET,
                   amplitude_range=SCOPE_RANGE)

        # Arm trigger
        scope.trigger(device_data,
                      enable=True,
                      source=scope.trigger_source.analog,
                      channel=TRIGGER_CHANNEL,
                      level=TRIGGER_LEVEL,
                      timeout=TRIGGER_TIMEOUT)

        try:
            raw = scope.record(device_data, channel=1)
        except Exception as e:
            print(f"  [!] Trace {i+1} failed: {e}")
            scope.close(device_data)
            failed += 1
            if failed > 10:
                print("  [!!] Too many failures — aborting")
                break
            continue
        finally:
            dwf.FDwfAnalogInReset(hdwf)
            scope.close(device_data)

        trace = np.array(raw)

        # Basic sanity check — if std is zero the buffer is stale
        if np.std(trace) < 1e-10:
            print(f"  [!] Trace {i+1}: zero variance — stale buffer, skipping")
            failed += 1
            sleep(INTER_TRACE_DELAY * 2)
            continue

        traces.append(trace)

        if (i + 1) % 10 == 0:
            swing_mv = (trace.max() - trace.min()) * 1000
            print(f"  {i+1:3d}/{num_traces}  "
                  f"swing: {swing_mv:.2f} mV  "
                  f"mean: {trace.mean():.4f} V")

        sleep(INTER_TRACE_DELAY)

    return np.array(traces)

# ── Plotting ───────────────────────────────────────────────────────────────────

def plot_results(traces, target_byte):
    hw = bin(target_byte).count('1')
    time_us = np.arange(traces.shape[1]) / SAMPLE_RATE * 1e6
    mean = np.mean(traces, axis=0)
    std  = np.std(traces, axis=0)

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))

    # Overlay
    ax = axes[0]
    for t in traces:
        ax.plot(time_us, t, color='#2196F3', linewidth=0.4, alpha=0.2)
    ax.plot(time_us, mean, color='#E53935', linewidth=1.5,
            label='Mean', zorder=5)
    ax.set_title(f'Overlay — 0x{target_byte:02X}  HW={hw}  ({len(traces)} traces)',
                 fontsize=13)
    ax.set_xlabel('Time [µs]'); ax.set_ylabel('Voltage [V]')
    ax.legend(); ax.grid(True, alpha=0.3)

    # Std deviation — peaks show instruction boundaries
    ax2 = axes[1]
    ax2.plot(time_us, std, color='#FF9800', linewidth=1.0)
    ax2.set_title('Std deviation — peaks = instruction-level switching events',
                  fontsize=11)
    ax2.set_xlabel('Time [µs]'); ax2.set_ylabel('Std [V]')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    path = f'{OUTPUT_DIR}/overlay_0x{target_byte:02X}.png'
    plt.savefig(path, dpi=200)
    print(f"[plot] → {path}")
    plt.show()

    return time_us

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    hw = bin(TARGET_BYTE).count('1')

    print(f"\n{'='*55}")
    print(f"  TARGET_BYTE : 0x{TARGET_BYTE:02X}  HW={hw}")
    print(f"  Clock       : {CLOCK_FREQ_HZ/1e6:.2f} MHz")
    print(f"  Samples/cycle: {SAMPLE_RATE/CLOCK_FREQ_HZ:.0f}")
    print(f"  Window      : {BUFFER_SIZE/SAMPLE_RATE*1e6:.0f} µs")
    print(f"{'='*55}\n")

    dwf = load_dwf()
    device_data = device.open()
    hdwf = device_data.handle

    try:
        clock_start(dwf, hdwf)
        sleep(2)

        print(f"[capture] Collecting {NUM_TRACES} traces ...\n")
        traces = collect_traces(device_data, NUM_TRACES, dwf, hdwf)

    finally:
        clock_stop(dwf, hdwf)
        device.close(device_data)

    if len(traces) == 0:
        print("[!] No traces captured — check wiring and firmware")
        return

    print(f"\n[done] {len(traces)} traces")
    print(f"       Voltage : {traces.min():.4f} – {traces.max():.4f} V")
    print(f"       Swing   : {(traces.max()-traces.min())*1000:.2f} mV")
    print(f"       Std     : {np.std(traces)*1000:.3f} mV")

    if np.std(traces) < 1e-6:
        print("\n[!!] Still zero variance — try increasing INTER_TRACE_DELAY to 0.05")
        return

    time_us = plot_results(traces, TARGET_BYTE)

    fname = f'{OUTPUT_DIR}/hw{hw}_byte0x{TARGET_BYTE:02X}_N{len(traces)}.npz'
    np.savez(fname, traces=traces, time_us=time_us,
             target_byte=TARGET_BYTE, hw=hw)
    print(f"[save] → {fname}")

if __name__ == '__main__':
    main()