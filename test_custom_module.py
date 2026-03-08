from WF_SDK import device, scope, error       # import instruments
import matplotlib.pyplot as plt
from time import sleep

"""-----------------------------------------------------------------------"""

try:
    # connect to the device
    device_data = device.open()

    """-----------------------------------"""

    # use instruments here
    if device_data.name != "Digital Discovery":
        scope.open(device_data, sampling_frequency=100e06, buffer_size=8192, offset=0, amplitude_range=6)

        # scope.trigger(device_data, enable=True, source=scope.trigger_source.analog, channel=2, level=3)
        sleep(1)
        buffer = scope.record(device_data, channel=1)

        time = []
        for index in range(len(buffer)):
            time.append(index*1e03/scope.data.sampling_frequency)

        print(buffer[0:15])

        plt.plot(time, buffer)
        plt.xlabel("time [ms]")
        plt.ylabel("voltage [V]")
        plt.show()

        scope.close(device_data)


    """-----------------------------------"""

    # close the connection
    device.close(device_data)

except error as e:
    print(e)
    # close the connection
    device.close(device.data)
