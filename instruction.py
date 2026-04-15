import os
from WF_SDK import device, scope, error
from ctypes import *
from time import sleep
import threading
import serial
import numpy as np


# ── Clock configuration ──────────────────────────────────────────────────────
CLOCK_FREQ_HZ   = 16e6    # 16 MHz
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

if __name__ == "__main__":
    counter = 0

    print("Testing with (0x00)")
    input_byte = 0
    ser = serial.Serial('/dev/ttyACM0', baudrate=9600, timeout=1)


    dwf = load_dwf()
    device_data = device.open()
    hdwf = device_data.handle

    clock_start(dwf, hdwf)
    sleep(10)

    while counter != 80:
        counter +=1

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

        buffer_holder = [None]

        def record():
            buffer_holder[0] = scope.record(device_data, channel=1)

        t = threading.Thread(target=record)
        t.start()
        sleep(0.1)

        ser.write(str(input_byte).encode() + b'\n')

        t.join(timeout=5)
        if t.is_alive():
            print(f"  [!] trace {counter} timed out — skipping")
            scope.close(device_data)
            sleep(0.5)
            continue
        # Process & save 
        buffer = buffer_holder[0]

        # Keep only the post-trigger half
        trigger_idx = len(buffer) // 2
        buffer = buffer[trigger_idx:]

        print(f"  samples captured: {len(buffer)}")

        np.savez(f'instruction/trace{input_byte}-{counter}.npz',
                    buffer=buffer,
                    password=np.frombuffer(str(input_byte).encode(), dtype=np.uint8))

        dwf.FDwfAnalogInReset(hdwf)
        print(counter)
        scope.close(device_data)
    print("80 traces of instruction captured")
    device.close(device.data)
    clock_stop(dwf, hdwf)