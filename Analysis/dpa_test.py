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
print(f'Loaded {len(traces)} traces, each {traces.shape[1]} samples')

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
print(f'Match distribution: {sorted(set(matches))}')

plt.figure(figsize=(20, 5))
for m in sorted(set(matches)):
    group = traces[[i for i, x in enumerate(matches) if x == m]]
    avg = np.mean(group, axis=0)
    plt.plot(avg, linewidth=0.8, alpha=0.7, label=f'{m} chars match')

plt.legend(fontsize=7)
plt.ylim(3.7, 4.6)
plt.title('Average trace per prefix match length')
plt.savefig('spa_average.png', dpi=150)

# split into two groups: 0 chars match vs 1+ chars match
group_0 = traces[[i for i, x in enumerate(matches) if x == 0]]
group_1 = traces[[i for i, x in enumerate(matches) if x >= 1]]

diff = np.mean(group_1, axis=0) - np.mean(group_0, axis=0)

plt.figure(figsize=(20, 5))
plt.plot(diff, color='red', linewidth=0.5)
plt.axhline(0, color='black', linewidth=0.5)
plt.title('DPA: Difference of means (0 match vs 1+ match)')
plt.savefig('dpa_diff.png', dpi=150)

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
