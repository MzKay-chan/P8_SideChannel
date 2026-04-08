import numpy as np
import os
import matplotlib as plt

class Analyser:
    alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789'
    actual_password = 'ilovecheese'

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

    @staticmethod
    def _save_plot(mean1, mean0, significant_string):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 10))

        # --- TOP GRAPH: Individual group means ---

        ax1.plot(mean1, color='red', linewidth=0.5, label=f'group1: {significant_string}')
        ax1.plot(mean0, color='blue', linewidth=0.5, label=f'group0: {significant_string[:-1]}[^{significant_string[-1]}]')
        ax1.set_title('Mean Power Consumption by Group', fontsize=14)
        ax1.set_ylabel('Power (mW)')
        ax1.legend(fontsize=7)
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(bottom=3.4, top=3.75)

        # --- BOTTOM GRAPH: Difference of means ---
        
        diff = mean1 - mean0
        ax2.plot(diff, color='red', linewidth=0.5, label='group1 - group0')
        ax2.set_title('Difference of Means', fontsize=14)
        ax2.set_ylabel('Power (mW)')
        ax2.set_xlabel('Time (samples)')
        ax2.legend(fontsize=7)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(f'dpa_plots/dpa_plot({significant_string}).png', dpi=150)

    def dpa(self, value_threshold=5, save_plots=True):
        if len(self.traces) == 0:
            raise ValueError('Need new traces to perform dpa')
        grouped_traces = self._group_by_character()
        group_indices = list(range(len(grouped_traces)))
        high_values = []
        list_of_differences = []
        for i in group_indices:
            average_group_1 = Analyser._average_groups_at_indices(grouped_traces, i)
            non_i_traces = [x for x in group_indices if x != i]
            average_group_0 = Analyser._average_groups_at_indices(grouped_traces, non_i_traces)
            group_difference = average_group_1 - average_group_0
            # for plotting later
            list_of_differences.append([average_group_0, average_group_1])
            # This gets the fifth largest value in the 'difference of means' trace (or whatever value_threshold is set to)
            # Hopefully this will prune out any weird values spikes
            high_values.append( np.partition( np.abs(group_difference), -value_threshold )[-value_threshold] )

        significant_group_index = high_values.index(max(high_values))

        #self.traces = []
        #self.passwords = []
        self.known_password += self.alphabet[significant_group_index]
        if save_plots:
            # save a plot for that found character
            Analyser._save_plot(
                list_of_differences[significant_group_index][1], 
                list_of_differences[significant_group_index][0], 
                self.known_password
            )
            # BUG FIXING: 
            if self.known_password not in self.actual_password:
                correct_letter = self.actual_password[len(self.known_password) - 1]
                correct_index = self.alphabet.index(correct_letter)
                Analyser._save_plot(
                    list_of_differences[correct_index][1],
                    list_of_differences[correct_index][0],
                    self.actual_password[:len(self.known_password) - 1]
                )
        return

    def plotschat(self):
        """
        DPA plot for the CURRENT recovered character.
        Only uses traces where previous characters are correct.
        """
        import matplotlib.pyplot as plt
        import numpy as np

        if len(self.traces) == 0:
            print("No traces loaded")
            return

        # Current position we just solved
        k = len(self.known_password) - 1
        if k < 0:
            print("No known characters yet")
            return

        correct_char = self.known_password[k]

        group0 = []  # wrong at position k
        group1 = []  # correct at position k

        # --- FILTER + GROUP ---
        for trace, password in zip(self.traces, self.passwords):

            # Only keep traces where prefix is correct
            if password[:k] != self.known_password[:k]:
                continue

            # Split on current position
            if password[k] == correct_char:
                group1.append(trace)
            else:
                group0.append(trace)

        if len(group0) == 0 or len(group1) == 0:
            print("Not enough valid traces after filtering")
            return

        group0 = np.array(group0)
        group1 = np.array(group1)

        # Means
        mean0 = np.mean(group0, axis=0)
        mean1 = np.mean(group1, axis=0)
        #meanall = np.mean(group1 + group0, axis=0)
        # Proper DPA
        diff = mean1 - mean0
        diff2 = mean1 - meanall
        # --- PLOT ---
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 10))

        # Means
        ax1.plot(mean0, color='black', linewidth=0.5, label='wrong')
        ax1.plot(mean1, color='red', linewidth=0.5, label='correct')

        ax1.set_title(f'DPA Means (Position {k}, char="{correct_char}")')
        ax1.set_ylabel('Power')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # DPA signal
        ax2.plot(diff, color='red', linewidth=0.7, label='correct - wrong')
        #ax2.plot(diff2, color='black', linewidth=0.7, label='correct - wrong')
        ax2.axhline(0, color='black', linewidth=0.5)

        ax2.set_title('DPA Signal')
        ax2.set_ylabel('Power Difference')
        ax2.set_xlabel('Time (samples)')
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()

        filename = f'dpa_pos{k}.png'
        plt.savefig(filename, dpi=150)
        print(f"Saved plot to {filename}")

        plt.close()

        # Reset for next round
        self.traces = []
        self.passwords = []

    def plots(self):
        """
        Create diagnostic plots for DPA analysis.
        Shows individual group means and difference of means for character hypotheses.
        """
        import matplotlib.pyplot as plt
        
        if len(self.traces) == 0:
            print("No traces loaded - cannot create plots")
            return
        
        # Group traces by character at current position
        grouped_traces = self._group_by_character()
        
        # Calculate mean for each character group
        char_grouped_means = self._average_every_group(grouped_traces)
        
        # Calculate overall mean (average of all traces)
        mean_all = np.mean(self.traces, axis=0)
        
        # Get the position we're currently attacking
        position = len(self.known_password)
        
        # Create figure with 2 subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 10))
        
        # --- TOP GRAPH: Individual group means for first few characters ---
        num_chars_to_plot = min(5, len(self.alphabet))  # Plot first 5 chars
        colors = ['red', 'green', 'blue', 'orange', 'purple']
        
        for i in range(num_chars_to_plot):
            if char_grouped_means[i] is not None and len(char_grouped_means[i]) > 0:
                ax1.plot(char_grouped_means[i], 
                        color=colors[i], 
                        linewidth=0.5, 
                        label=f"'{self.alphabet[i]}' match",
                        alpha=0.7)
        
        ax1.axhline(0, color='black', linewidth=0.5)
        ax1.set_title(f'DPA: Mean Power Consumption by Character at Position {position}', fontsize=14)
        ax1.set_ylabel('Power (V)')
        ax1.set_xlabel('Time (samples)')
        ax1.legend(fontsize=9)
        ax1.grid(True, alpha=0.3)
        
        # --- BOTTOM GRAPH: Difference of means ---
        for i in range(num_chars_to_plot):
            if char_grouped_means[i] is not None and len(char_grouped_means[i]) > 0:
                diff = char_grouped_means[i] - mean_all
                ax2.plot(diff, 
                        color=colors[i], 
                        linewidth=0.5, 
                        label=f"'{self.alphabet[i]}' - mean",
                        alpha=0.7)
        
        ax2.axhline(0, color='black', linewidth=0.5)
        ax2.set_title('DPA: Difference of Means (Signal)', fontsize=14)
        ax2.set_ylabel('Power Difference (V)')
        ax2.set_xlabel('Time (samples)')
        ax2.legend(fontsize=9)
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Save with position indicator
        filename = f'dpa_analysis_pos{position}.png'
        plt.savefig(filename, dpi=150)
        print(f"Saved plot to {filename}")
        plt.close()
        self.traces = []
        self.passwords = []
        return


