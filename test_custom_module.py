from WF_SDK import device, scope, error       # import instruments
import string, random
import serial
import matplotlib.pyplot as plt
import numpy as np
import threading
from time import sleep
import os

"""-----------------------------------------------------------------------"""

try:
    os.makedirs('traces', exist_ok=True)

    # connect to the device
    ser = serial.Serial('/dev/ttyACM0', baudrate=9600, timeout=1)
    
    #For testing a simple set of password
    passwords = ["iAAAAAAAAAA", "ilAAAAAAAAA"]

    #Generate all the passwords that we want to test
    # passwords = []
    #
    # # 1. fully random passwords (baseline noise)
    # for _ in range(50):
    #     passwords.append(''.join(random.choices(string.ascii_lowercase, k=random.randint(1, 19))))
    #
    # # 2. passwords with increasing correct prefix
    # for length in range(1, len(known)+1):
    #     for _ in range(5):  # 5 traces per prefix length
    #         prefix = known[:length]
    #         # add random suffix to keep length variable
    #         suffix = ''.join(random.choices(string.ascii_lowercase, k=random.randint(0, 5)))
    #         passwords.append(prefix + suffix)
    #
    # random.shuffle(passwords)  # shuffle so pattern isn't time-dependent

    for i in range(len(passwords)):
        #Open everything

        device_data = device.open()
        #Start the oscilliscope
        scope.open(device_data, sampling_frequency=100e06, buffer_size=8192, offset=0, amplitude_range=6)

        #Prep for the trigger event
        scope.trigger(device_data, enable=True, source=scope.trigger_source.analog, channel=2, level=3)

        buffer_holder = [None]

        print("going into while loop")
        #Wait for the arduino to be ready
        while True:
            response = ser.readline()
            print(response.strip())
            if response.strip() == b"Enter Password:":
                print("Check")
                break
            
        print(f'Arduino: {response.strip()}')

        def record():
            buffer_holder[0] = scope.record(device_data, channel=1)

        t = threading.Thread(target=record)
        t.start()
        #Small delay to ensure the scope is armed
        sleep(0.5)

 
        print(f'Sending password: {passwords[i]}')
        ser.write((passwords[i] + '\n').encode())
        resp = ser.readline()
        print(resp)

        t.join(timeout=5)
        if t.is_alive():
            print(f"Trace {i}: timed out")
            continue

        print("Trace recieved")     
        buffer = buffer_holder[0]
        trigger_idx = len(buffer) //2 
        buffer = buffer[trigger_idx:]

        print(len(buffer))
        #Read arduino response 
        print('saving') 
        np.savez(f'traces/trace{i}.npz',
                 buffer=buffer,
                 password=np.frombuffer(passwords[i].encode(), dtype=np.uint8))

        #Uncomment to get graphs for each trace
        time = [i * 1e03 / scope.data.sampling_frequency for i in range(len(buffer))]
        plt.figure()
        plt.xlim(0, 0.022)  # x range in ms
        plt.ylim(3.9, 4.5)  # y range in volts
        plt.plot(time, buffer, color='#2196F3', linewidth=0.5, alpha=0.8)
        plt.title(f'Post trigger only{i}')
        plt.xlabel(f"time [ms] - Pass:{passwords[i]}")
        plt.ylabel("voltage [V]")
        plt.savefig(f'test_trace{i}', dpi = 250)
        #plt.show()
        buffer = None

        print('closing the scope?')
        scope.close(device_data)
        device.close(device_data)
        sleep(1)


except error as e:
    print(e)
    # close the connection
    device.close(device.data)
