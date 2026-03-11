# Side Channel Analysis - Semester 8 Project

A practical introduction to power analysis attacks on embedded systems, using an Arduino Uno as the target device and a Digilent Analog Discovery 2 as the measurement instrument.

## Overview

This project explores Simple Power Analysis (SPA) and Differential Power Analysis (DPA) by capturing power traces from an Arduino Uno during password comparison operations. The goal is to investigate whether power consumption leaks information about the secret password.

## Hardware Setup

| Component | Role |
|---|---|
| Arduino Uno | Target device running password comparison sketch |
| Digilent Analog Discovery 2 | USB oscilloscope for capturing power traces |
| Shunt resistor (10-50Ω) | Inserted in Arduino power line to measure current draw |

Both devices connect to the same PC via USB, sharing a common ground through the host machine.

- **CH1** measures voltage across the shunt resistor (power trace)
- **CH2** receives the trigger signal from an Arduino GPIO pin

## Software & Libraries

### WaveForms SDK (`WF_SDK`)
Python wrapper for the Digilent WaveForms SDK, used to control the Analog Discovery 2 programmatically.
- **Install:** [Digilent WaveForms](https://digilent.com/reference/software/waveforms/waveforms-3/start)
- **Usage:** `from WF_SDK import device, scope`
- Configures sampling frequency, buffer size, trigger source, and records traces

### PySerial
Used to communicate with the Arduino over USB serial.
```bash
pip install pyserial
```

### Other Dependencies
```bash
pip install numpy matplotlib
```

## How It Works

1. Python script arms the oscilloscope and waits for a trigger
2. A random password is sent to the Arduino over serial
3. Arduino receives the password, raises the trigger pin HIGH, and runs the comparison
4. Scope captures the power trace on CH1, triggered by CH2
5. Trace and password are saved together as a `.npz` file

## File Structure

```
project/
├── test_custom_module.py       # Main trace collection script
├── analysis.py                 # SPA/DPA analysis script
├── traces/                     # Collected traces (.npz files)
│   ├── trace0.npz
│   ├── trace1.npz
│   └── ...
└── Arduino_sketchs/
    └── sketch_handbook_example1/
        └── sketch_handbook_example1.ino
```

## Trace Format

Each `.npz` file contains:
- `buffer` — power trace samples (float64)
- `password` — the password sent for that trace (uint8 array)

Load with:
```python
import numpy as np
data = np.load('traces/trace0.npz')
buffer = data['buffer']
password = data['password'].tobytes().decode()
```

## Analysis

### SPA
Overlay averaged traces grouped by prefix match length to visually identify power differences.

### DPA (Difference of Means)
Split traces into two groups based on a hypothesis (e.g. 0 chars match vs 1+ chars match) and compute the difference of means across all time samples. A spike indicates a sample where power consumption correlates with the hypothesis.

## Notes

- Trigger point is at `len(buffer) // 2` — the scope places it at the midpoint of the buffer
- Sampling frequency: 100 MHz, buffer size: 8192 samples
- Arduino baudrate: 9600
- Known password: `ilovecheese`
