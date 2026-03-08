from WF_SDK import device, scope, error       # import instruments
import matplotlib.pyplot as plt
import numpy as np
from time import sleep

"""-----------------------------------------------------------------------"""

try:
    # connect to the device
    device_data = device.open()

    """-----------------------------------"""

    # use instruments here
    if device_data.name != "Digital Discovery":
        scope.open(device_data, sampling_frequency=100e06, buffer_size=8192, offset=0, amplitude_range=6)

        scope.trigger(device_data, enable=True, source=scope.trigger_source.analog, channel=2, level=3)
        buffer = scope.record(device_data, channel=1)
        # buffer_trigger = scope.record(device_data, channel=2)
         
        # trigger_idx = next((i for i, v in enumerate(buffer_trigger) if v >= 3), 0)

        # buffer = buffer[trigger_idx:]

        time = []
        for index in range(len(buffer)):
            time.append(index*1e03/scope.data.sampling_frequency)

        np.savez('trace.npz',
                 buffer=buffer,
                 time=time,
                 sampling_frequency=scope.data.sampling_frequency)

        print(buffer[0:15])

        plt.figure(20)
        plt.plot(time, buffer, color='#2196F3', linewidth=0.5, alpha=0.8)
        plt.xlabel("time [ms]")
        plt.ylabel("voltage [V]")
        plt.savefig('test_trace', dpi = 250)
        #plt.show()

        scope.close(device_data)


    """-----------------------------------"""

    # close the connection
    device.close(device_data)

except error as e:
    print(e)
    # close the connection
    device.close(device.data)
