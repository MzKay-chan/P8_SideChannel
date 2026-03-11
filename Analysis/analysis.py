import numpy as np

class analyser:
    def __init__(self, measurements, time):
        self.measurements = measurements
        self.time = time
        return

    def _prepare_data(self, mid_point=0.5):
        data_lengths = []
        # remove the first half of the data
        mid_index = int(len(self.time) * mid_point)
        self.time = self.time[mid_index:]
        data_lengths.append(len(self.time))

        for i in range(len(self.measurements)):
            self.measurements[i] = self.measurements[i][mid_index:]
            data_lengths.append(len(self.measurements[i]))

        # ensure all data arrays have the same length
        min_length = min(data_lengths)
        self.time = self.time[:min_length]
        for i in range(len(self.measurements)):
            self.measurements[i] = self.measurements[i][:min_length]
        return

    def _significant_difference(self, measurements1, measurements2, threshold=0.05):
        # get the difference between the two measurements
        measurement_difference = measurements1 - measurements2
        significant_diff = np.abs(measurement_difference) > threshold

        if np.any(significant_diff):
            return self.time[np.where(significant_diff)[0][0]] # return the first time point where the significant difference occurs
        return self.time[-1] # no significant difference found, so return the last time point

    def spa_find_length(self, threshold=0.05, max_length=20):
        # make sure we have the right number of traces
        if len(self.measurements) != max_length:
             raise ValueError(f"Expected {max_length} measurements, but got {len(self.measurements)}")
        self._prepare_data()

        # get the first significant difference for each measurement compared to the null password measurement
        first_differences = []
        for i in range(1, max_length):
            first_differences.append(
                self._significant_difference(self.measurements[0], self.measurements[i], threshold=threshold)
            )
        
        return first_differences
