import numpy as np
import matplotlib.pyplot as plt
import os

known = "ilovecheese"

# load all traces
traces = []
passwords = []
for f in sorted(os.listdir('traces')):
    if not f.endswith('.npz'):
        continue
    data = np.load(f'traces/{f}')
    traces.append(data['buffer'])
    passwords.append(data['password'].tobytes().decode())
traces = np.array(traces)
print(f'Loaded {len(traces)} traces in traces, each {traces.shape[1]} samples')

# compute how many characters each password matches
def prefix_match(pwd, known):
    count = 0
    for a, b in zip(pwd, known):
        if a == b:
            count += 1
        else:
            break
    return count
matches = [prefix_match(p, known) for p in passwords]

# print every password and how many chars it matches
for p in passwords:
    print(f'{p} matches {prefix_match(p, known):>2} chars')

# display the distribution of each type of password
for m in sorted(set(matches)):
    count = matches.count(m)
    print(f'{count:>2} passwords with {m:>2} chars match')

# see how many passwords had the wrong length (should be 0 for this implementation)
wrong_length_counter = 0
for p in passwords:
    if len(p) != len(known):
        wrong_length_counter += 1
print(f'{wrong_length_counter} passwords had wrong length')

# split the traces into groups based on the number of matches
group_0_mean = np.mean(traces[[i for i, x in enumerate(matches) if x == 0]], axis=0)
group_1_mean = np.mean(traces[[i for i, x in enumerate(matches) if x >= 1]], axis=0)
grouped_traces = []
for m in sorted(set(matches)):
    group = traces[[i for i, x in enumerate(matches) if x == m]]
    grouped_traces.append(group)
group_means = [np.mean(group, axis=0) for group in grouped_traces]

# split the traces into groups based on the first character
char_grouped_traces = []
for c in sorted(set(p[0] for p in passwords)):
    group = traces[[i for i, p in enumerate(passwords) if p[0] == c]]
    char_grouped_traces.append(group)
char_grouped_means = [np.mean(group, axis=0) for group in char_grouped_traces]

mean_all = np.mean(traces, axis=0)

# choose which graph to display
display_graph = 5
match display_graph:
    case 1:
        diff = group_1_mean - group_0_mean
        plt.figure(figsize=(20, 5))
        plt.plot(diff, color='red', linewidth=0.5)
        plt.title('DPA: Difference of means (group_1 - group_0)')
        plt.savefig('dpa_diff_+1.png', dpi=150)
        plt.show()
    case 2:
        # Create a figure with 2 subplots stacked vertically
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 10))

        # --- TOP GRAPH: Individual group means ---

        ax1.plot(group_means[0], color='black', linewidth=0.5, label='0 matches')
        ax1.plot(group_means[1], color='red', linewidth=0.5, label='1 match')
        # ax1.plot(group_means[2], color='green', linewidth=0.5, label='2 matches')
        # ax1.plot(group_means[3], color='blue', linewidth=0.5, label='3 matches')
        ax1.axhline(0, color='black', linewidth=0.5)
        ax1.set_title('DPA: Mean Power Consumption by Group', fontsize=14)
        ax1.set_ylabel('Power (mW or arbitrary units)')
        ax1.legend(fontsize=7)
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(bottom=3.4, top=3.75)

        # --- BOTTOM GRAPH: Difference of means (your original code) ---
        diff1 = group_means[1] - group_means[0]
        #diff2 = group_means[2] - group_means[0]
        # diff3 = group_means[3] - group_means[0]

        ax2.plot(diff1, color='red', linewidth=0.5, label='1 match - 0 match')
        # ax2.plot(diff2, color='green', linewidth=0.5, label='2 matches - 0 match')
        # ax2.plot(diff3, color='blue', linewidth=0.5, label='3 matches - 0 match')
        ax2.axhline(0, color='black', linewidth=0.5)
        ax2.set_title('DPA: Difference of Means', fontsize=14)
        ax2.set_ylabel('Power Difference')
        ax2.set_xlabel('Time (samples)')
        ax2.legend(fontsize=7)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig('dpa_diff.png', dpi=150)
        plt.show()
    case 3:
        # Create a figure with 2 subplots stacked vertically
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 10))

        # --- TOP GRAPH: Individual group means ---

        ax1.plot(char_grouped_means[8], color='red', linewidth=0.5, label='i match')
        ax1.plot(char_grouped_means[9], color='green', linewidth=0.5, label='j match')
        ax1.plot(char_grouped_means[10], color='blue', linewidth=0.5, label='k match')
        ax1.axhline(0, color='black', linewidth=0.5)
        ax1.set_title('DPA: Mean Power Consumption by Group', fontsize=14)
        ax1.set_ylabel('Power (mW or arbitrary units)')
        ax1.legend(fontsize=7)
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(bottom=3.43, top=3.65)

        # --- BOTTOM GRAPH: Difference of means (your original code) ---
        diff1 = char_grouped_means[8] - mean_all
        diff2 = char_grouped_means[9] - mean_all
        diff3 = char_grouped_means[10] - mean_all

        ax2.plot(diff1, color='red', linewidth=0.5, label='1 match - 0 match')
        ax2.plot(diff2, color='green', linewidth=0.5, label='2 matches - 0 match')
        ax2.plot(diff3, color='blue', linewidth=0.5, label='3 matches - 0 match')
        ax2.axhline(0, color='black', linewidth=0.5)
        ax2.set_title('DPA: Difference of Means', fontsize=14)
        ax2.set_ylabel('Power Difference')
        ax2.set_xlabel('Time (samples)')
        ax2.legend(fontsize=7)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig('dpa_diff.png', dpi=150)
        plt.show()
    case 4:
        # measure where the signal drops back to baseline after trigger spike
        # proxy for how long the comparison took
        def find_end(trace, threshold=4.15):
            for i in range(len(trace)-1, 0, -1):
                if trace[i] < threshold:
                    return i
            return len(trace)

        timings = [find_end(t) for t in traces]

        plt.figure(figsize=(10, 5))
        plt.scatter(matches, timings, alpha=0.6)
        plt.xlabel('Prefix match length')
        plt.ylabel('Comparison end sample')
        plt.title('Timing vs prefix match length')
        plt.savefig('timing.png', dpi=150)
    case 5:
        from analysis import Analyser
        analyser = Analyser()
        analyser.load_new_traces('traces')
        print(analyser.known_password)
        analyser.dpa()
        print(analyser.known_password)



