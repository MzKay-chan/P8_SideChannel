import numpy as np 

class analyser:
    def __init__(self):
        return

    def _prepare_data(self, measurements, time, mid_point=0.5):
        # remove the first half of the data
        mid_point = int(len(measurements) * mid_point)
        return measurements[mid_point:], time[mid_point:]
    
    def significant_difference(self, measurements1, time1, measurements2, time2, threshold=0.05):
        # prepare the data by removing the first half of the measurements and time points
        measurements1, time1 = self._prepare_data(measurements1, time1)
        measurements2, time2 = self._prepare_data(measurements2, time2)

        # ensure both measurement lists are of the same length
        if len(measurements1) < len(measurements2):
            measurements2 = measurements2[:len(measurements1)]
            time2 = time2[:len(measurements1)]
        elif len(measurements2) < len(measurements1):
            measurements1 = measurements1[:len(measurements2)]
            time1 = time1[:len(measurements2)]

        measurement_difference = np.array(measurements1) - np.array(measurements2)
        significant_diff = np.abs(measurement_difference) > threshold
        
        if np.any(significant_diff):
            return time1[np.where(significant_diff)[0][0]] # return the first time point where the significant difference occurs
        return False # no significant difference found
    

    