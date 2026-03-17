from WF_SDK import device, scope, error       # import instruments
from ctypes import *
import string, random
import serial
import matplotlib.pyplot as plt
import numpy as np
import threading
from time import sleep
import os

"""-----------------------------------------------------------------------"""

# ── Clock configuration ──────────────────────────────────────────────────────
CLOCK_FREQ_HZ   = 16e6      # 1 MHz — safe starting point, raise to 16e6 later
CLOCK_AMPLITUDE = 2.5     # V  → gives a 0–3.3 V swing on XTAL1
CLOCK_OFFSET    = 2.5     # V

def load_dwf():
    """Load the WaveForms runtime library for the current platform."""
    import sys
    if sys.platform == "win32":
        return cdll.LoadLibrary("dwf.dll")
    elif sys.platform == "darwin":
        return cdll.LoadLibrary("/Library/Frameworks/dwf.framework/dwf")
    else:
        return cdll.LoadLibrary("libdwf.so")

def clock_start(dwf, hdwf):
    """
    Configure W1 as a square-wave clock and start it.
    Call once after FDwfDeviceOpen.
    """
    ch = c_int(0)          # W1 = channel 0
    node = c_int(0)        # carrier node

    dwf.FDwfAnalogOutNodeEnableSet(hdwf, ch, node, c_bool(True))
    dwf.FDwfAnalogOutNodeFunctionSet(hdwf, ch, node, c_int(1))   # 1 = square
    dwf.FDwfAnalogOutNodeFrequencySet(hdwf, ch, node,
                                      c_double(CLOCK_FREQ_HZ))
    dwf.FDwfAnalogOutNodeAmplitudeSet(hdwf, ch, node,
                                      c_double(CLOCK_AMPLITUDE))
    dwf.FDwfAnalogOutNodeOffsetSet(hdwf, ch, node,
                                   c_double(CLOCK_OFFSET))
    dwf.FDwfAnalogOutConfigure(hdwf, ch, c_bool(True))
    print(f"[clock] W1 running at {CLOCK_FREQ_HZ/1e6:.1f} MHz")

def clock_stop(dwf, hdwf):
    """Stop W1 output cleanly."""
    dwf.FDwfAnalogOutConfigure(hdwf, c_int(0), c_bool(False))
    print("[clock] W1 stopped")

def clock_glitch(dwf, hdwf, glitch_freq=100e6, duration_s=1e-6):
    """
    Momentary frequency spike — basic clock glitch.
    glitch_freq : frequency to spike to (Hz)
    duration_s  : how long to hold the spike (seconds)
    """
    ch   = c_int(0)
    node = c_int(0)
    dwf.FDwfAnalogOutNodeFrequencySet(hdwf, ch, node, c_double(glitch_freq))
    dwf.FDwfAnalogOutConfigure(hdwf, ch, c_bool(True))
    sleep(duration_s)
    dwf.FDwfAnalogOutNodeFrequencySet(hdwf, ch, node, c_double(CLOCK_FREQ_HZ))
    dwf.FDwfAnalogOutConfigure(hdwf, ch, c_bool(True))

# ─────────────────────────────────────────────────────────────────────────────

try:
    os.makedirs('traces', exist_ok=True)

    # Load WaveForms DWF library (needed for clock control)
    dwf = load_dwf()

    # Open serial connection to Arduino
    ser = serial.Serial('/dev/ttyACM0', baudrate=9600, timeout=1)
    sleep(2)
    ser.reset_input_buffer()
    ser.write(b'\n')
    sleep(0.1)
    ser.reset_input_buffer()

    # ── Password list ────────────────────────────────────────────────────────
    # Simple test set — uncomment the generator block below for a full campaign
    # passwords = ["iAAAAAAAAAA", "ilAAAAAAAAA"]

    known = "ilovecheese"   # ← set your known prefix here when doing a real run
    passwords = []

    # 1. fully random passwords (baseline noise)
    for _ in range(50):
        passwords.append(''.join(random.choices(string.ascii_lowercase, k=11)))

    # 2. passwords with increasing correct prefix
    for length in range(1, len(known)):
        for _ in range(5):  # 5 traces per prefix length
            prefix = known[:length]
            space = 11 - len(prefix)
            suffix = ''.join(random.choices(string.ascii_lowercase,
                                            k=space))
            passwords.append(prefix + suffix)

    random.shuffle(passwords)

    # ── Main capture loop ────────────────────────────────────────────────────
    for i, password in enumerate(passwords):

        print(f"\n[{i+1}/{len(passwords)}] password: {password}")

        # Open AD2 — we do this per-iteration (same as before) so the scope
        # resets cleanly; clock is restarted each time too.
        device_data = device.open()

        # Grab the raw dwf handle so we can call wavegen directly
        hdwf = device_data.handle   # WF_SDK exposes .handle as a c_int

        # Start the clock on W1 → ATmega XTAL1 (pin 9)
        clock_start(dwf, hdwf)

        # Give the ATmega a moment to stabilise on the new clock
        sleep(0.1)

        # Start oscilloscope
        scope.open(device_data,
                   sampling_frequency=100e6,
                   buffer_size=8192,
                   offset=0,
                   amplitude_range=6)

        # Arm trigger — rising edge on CH2 at 3 V (your trigger line)
        scope.trigger(device_data,
                      enable=True,
                      source=scope.trigger_source.analog,
                      channel=2,
                      level=3,
                      timeout=3)

        # ── Wait for Arduino prompt ──────────────────────────────────────────
        print("  waiting for Arduino prompt …")
        while True:
            response = ser.read_until(b"Enter Password:")
            if b"Enter Password:" in response:
                print("  Arduino ready")
                break

        # ── Arm scope in background thread ───────────────────────────────────
        buffer_holder = [None]

        def record():
            buffer_holder[0] = scope.record(device_data, channel=1)

        t = threading.Thread(target=record)
        t.start()

        # Short arm delay — kept at 0.1 s (was 0.5 s) since the scope is
        # already configured above; this just lets the thread enter the
        # blocking record() call before we send the password.
        sleep(0.1)

        # ── Send password & collect trace ────────────────────────────────────
        ser.write((password + '\n').encode())
        arduino_resp = ser.readline()
        print(f"  Arduino: {arduino_resp.strip()}")

        t.join(timeout=5)
        if t.is_alive():
            print(f"  [!] trace {i} timed out — skipping")
            scope.close(device_data)
            clock_stop(dwf, hdwf)
            device.close(device_data)
            sleep(0.5)
            continue

        # ── Process & save ───────────────────────────────────────────────────
        buffer = buffer_holder[0]

        # Keep only the post-trigger half
        trigger_idx = len(buffer) // 2
        buffer = buffer[trigger_idx:]

        print(f"  samples captured: {len(buffer)}")

        np.savez(f'traces/trace{i}.npz',
                 buffer=buffer,
                 password=np.frombuffer(password.encode(), dtype=np.uint8))

        # ── Plot ─────────────────────────────────────────────────────────────
        time_axis = [s * 1e3 / scope.data.sampling_frequency
                     for s in range(len(buffer))]
        plt.figure()
        plt.xlim(0, 0.022)
        plt.ylim(3.9, 4.5)
        plt.plot(time_axis, buffer,
                 color='#2196F3', linewidth=0.5, alpha=0.8)
        plt.title(f'Post-trigger trace {i}')
        plt.xlabel(f"time [ms]  —  pass: {password}")
        plt.ylabel("voltage [V]")
        plt.savefig(f'test_trace{i}', dpi=250)
        plt.close()   # free memory — important in long campaigns

        # ── Tear down for this iteration ─────────────────────────────────────
        scope.close(device_data)
        clock_stop(dwf, hdwf)
        device.close(device_data)

        buffer = None
        sleep(0.5)   # reduced from 1 s — clock restart gives the chip time

    print("\n[done] all traces captured")

except error as e:
    print(e)
    device.close(device.data)
