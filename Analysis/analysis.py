import numpy as np
import os

class Analyser:
    alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789'

    def __init__(self):
        self.known_password = ''
        self.traces = []
        self.passwords = []

    def load_new_traces(self, trace_folder):
        self.traces = []
        self.passwords = []
        for f in sorted(os.listdir(trace_folder)):
            if not f.endswith('.npz'):
                continue
            data = np.load(f'{trace_folder}/{f}')
            self.traces.append(data['buffer'])
            self.passwords.append(data['password'].tobytes().decode())
        self.traces = np.array(self.traces)
        print(f'Loaded {len(self.traces)} traces in traces, each {self.traces.shape[1]} samples')

    def _group_by_character(self):
        index = len(self.known_password)
        char_grouped_traces = np.array([None]*len(self.alphabet))
        for i, c in enumerate(self.alphabet):
            group = self.traces[[i for i, p in enumerate(self.passwords) if p[index] == c]]
            char_grouped_traces[i] = group
        return char_grouped_traces

    def _group_by_matches(self):
        def prefix_match(pwd, known):
            count = 0
            for a, b in zip(pwd, known):
                if a == b:
                    count += 1
                else:
                    break
            return count
        matches = [prefix_match(p, self.known_password) for p in self.passwords]
        grouped_traces = []
        for m in sorted(set(matches)):
            group = self.traces[[i for i, x in enumerate(matches) if x == m]]
            grouped_traces.append(group)
        return grouped_traces

    @staticmethod
    def _average_every_group(grouped_traces):
        return [np.mean(group, axis=0) for group in grouped_traces]

    @staticmethod
    def _average_groups_at_indices(grouped_traces, indices):
        # check if indices is a list, else: it's a single index
        if isinstance(indices, list):
            new_grouped_traces = []
            for i in indices:
                if i >= len(grouped_traces) or i < 0:
                    raise ValueError(f'Index {i} out of range for grouped_traces of length {len(grouped_traces)}')
                for t in range(len(grouped_traces[i])):
                    new_grouped_traces.append(grouped_traces[i][t])
            return np.mean(new_grouped_traces, axis=0)
        else:
            return np.mean(grouped_traces[indices], axis=0)

    def dpa(self, value_threshold=5):
        if len(self.traces) == 0:
            raise ValueError('Need new traces to perform dpa')
        grouped_traces = self._group_by_character()
        group_indices = list(range(len(grouped_traces)))
        high_values = []
        for i in group_indices:
            index_average = Analyser._average_groups_at_indices(grouped_traces, i)
            nonindex_trace_indices = [x for x in group_indices if x != i]
            nonindex_average = Analyser._average_groups_at_indices(grouped_traces, nonindex_trace_indices)
            index_difference = index_average - nonindex_average
            # This gets the fifth largest value in the 'difference of means' trace (or whatever value_threshold is set to)
            # Hopefully this will prune out any weird values spikes
            high_values.append( np.partition( np.abs(index_difference), -value_threshold )[-value_threshold] )

        significant_trace = high_values.index(max(high_values))
        self.traces = []
        self.passwords = []
        self.known_password += self.alphabet[significant_trace]
        return

