import os
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats

# ── Configuration ─────────────────────────────────────────────────────────────
SAVE_DIR      = "tvla_traces"       # folder from tvla_capture.py
PLOT_DIR      = "tvla_plots"
T_THRESHOLD   = 4.5                 # standard TVLA pass/fail threshold
SAMPLE_RATE   = 100e6               # Hz  (100 MHz AD2 sample rate)
CLOCK_FREQ    = 1e6                 # Hz  (1 MHz ATmega clock)
SAMPLES_PER_CYCLE = int(SAMPLE_RATE / CLOCK_FREQ)   # = 100 samples per clock cycle

os.makedirs(PLOT_DIR, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
def time_axis(n_samples: int) -> np.ndarray:
    """Return a time axis in microseconds."""
    return np.arange(n_samples) / SAMPLE_RATE * 1e6


def cycle_boundaries(n_samples: int) -> np.ndarray:
    """Return sample indices at each clock cycle boundary."""
    return np.arange(0, n_samples, SAMPLES_PER_CYCLE)


def align_traces(traces: np.ndarray, search_window: int = 200) -> np.ndarray:
    """
    Align all traces to the first rising edge of the clock
    found within the first `search_window` samples after trigger.
    This gives an absolute reference independent of trace content.
    """
    aligned = []
    for tr in traces:
        # Find the first rising edge: look for sample where signal
        # crosses upward through the midpoint of its range
        window    = tr[:search_window]
        mid       = (window.max() + window.min()) / 2
        # Rising edge = sample where we go from below mid to above mid
        crossings = np.where((window[:-1] < mid) & (window[1:] >= mid))[0]
        
        if len(crossings) == 0:
            # No edge found — just append as-is
            aligned.append(tr)
            continue
        
        edge = crossings[0]  # first rising edge position
        # Trim everything before the edge so all traces start at same phase
        aligned.append(tr[edge:])
    
    # Traces may now have slightly different lengths — trim to shortest
    min_len = min(len(t) for t in aligned)
    return np.array([t[:min_len] for t in aligned], dtype=np.float32)


def welch_ttest(fixed: np.ndarray, random: np.ndarray) -> np.ndarray:
    """
    Run Welch t-test independently at every sample point.
    Returns t-statistic array, shape (n_samples,).
    """
    t_stat, _ = stats.ttest_ind(fixed, random, axis=0, equal_var=False)
    return t_stat


def compute_snr(traces: np.ndarray, vals: np.ndarray) -> np.ndarray:
    """
    Signal-to-Noise Ratio per sample point.
    SNR[s] = Var(group means at s) / mean(Var within groups at s)
    A high SNR at sample s means power at that point strongly
    separates different input values — i.e., that sample leaks.
    """
    unique_vals = np.unique(vals)
    group_means = []
    group_vars  = []
    for v in unique_vals:
        group = traces[vals == v]
        if len(group) < 2:
            continue
        group_means.append(group.mean(axis=0))
        group_vars.append(group.var(axis=0))
    group_means = np.array(group_means)
    group_vars  = np.array(group_vars)
    signal      = group_means.var(axis=0)
    noise       = group_vars.mean(axis=0)
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(noise > 0, signal / noise, 0.0)


# ── Load data ─────────────────────────────────────────────────────────────────
print("[load] Reading traces...")
fixed_traces  = np.load(os.path.join(SAVE_DIR, "fixed_traces.npy"))
random_traces = np.load(os.path.join(SAVE_DIR, "random_traces.npy"))
random_vals   = np.load(os.path.join(SAVE_DIR, "random_vals.npy"))
fixed_val     = np.load(os.path.join(SAVE_DIR, "fixed_val.npy"))[0]

print(f"  fixed_traces  : {fixed_traces.shape}")
print(f"  random_traces : {random_traces.shape}")
print(f"  random_vals   : {random_vals.shape}  "
      f"unique={len(np.unique(random_vals))}/256")

print(f"  fixed value   : 0x{fixed_val:02X}\n")

n_samples = fixed_traces.shape[1]
t_axis    = time_axis(n_samples)
cycles    = cycle_boundaries(n_samples)

# ── Step 1 — Alignment ────────────────────────────────────────────────────────
print("[align] Aligning traces via cross-correlation...")
fixed_traces  = align_traces(fixed_traces)
random_traces = align_traces(random_traces)

# ── NEW: ensure both groups have identical length ──
min_len       = min(fixed_traces.shape[1], random_traces.shape[1])
fixed_traces  = fixed_traces[:,  :min_len]
random_traces = random_traces[:, :min_len]
print(f"  Trimmed to {min_len} samples per trace\n")

n_samples = fixed_traces.shape[1]   # recompute after trimming
t_axis    = time_axis(n_samples)
cycles    = cycle_boundaries(n_samples)

# ── Step 2 — Mean traces and difference ──────────────────────────────────────
mean_fixed  = fixed_traces.mean(axis=0)
mean_random = random_traces.mean(axis=0)
difference  = mean_fixed - mean_random

# ── Step 3 — Welch t-test (TVLA) ─────────────────────────────────────────────
print("[tvla] Running Welch t-test...")
t_stat = welch_ttest(fixed_traces, random_traces)

leaky_samples = np.where(np.abs(t_stat) > T_THRESHOLD)[0]
leaky_cycles  = np.unique(leaky_samples // SAMPLES_PER_CYCLE)

if len(leaky_samples) == 0:
    print(f"  RESULT: NO leakage detected  (|t| never exceeds {T_THRESHOLD})")
else:
    print(f"  RESULT: LEAKAGE DETECTED at {len(leaky_samples)} sample points")
    print(f"  Leaky clock cycles (0-indexed) : {leaky_cycles.tolist()}")
    print(f"  Max |t|  = {np.max(np.abs(t_stat)):.2f}  "
          f"at sample {np.argmax(np.abs(t_stat))}")
print()

# ── Step 4 — SNR ─────────────────────────────────────────────────────────────
print("[snr] Computing SNR on random traces...")
snr_vals = compute_snr(random_traces, random_vals)
peak_snr  = snr_vals.max()
peak_snr_cyc = snr_vals.argmax() // SAMPLES_PER_CYCLE
print(f"  Peak SNR = {peak_snr:.4f}  at cycle {peak_snr_cyc}\n")

# ── Step 5 — Hamming Weight correlation ──────────────────────────────────────
print("[hw] Computing Hamming Weight correlation...")
hw_vals  = np.array([bin(v).count('1') for v in random_vals], dtype=np.float32)
hw_corr  = np.array([
    np.corrcoef(hw_vals, random_traces[:, s])[0, 1]
    for s in range(n_samples)
])
peak_hw_corr = np.max(np.abs(hw_corr))
peak_hw_cyc  = np.argmax(np.abs(hw_corr)) // SAMPLES_PER_CYCLE
print(f"  Peak |HW correlation| = {peak_hw_corr:.4f}  at cycle {peak_hw_cyc}\n")

# ── Step 6 — HW linear regression at peak sample ─────────────────────────────
peak_sample   = int(np.argmax(np.abs(hw_corr)))
power_at_peak = random_traces[:, peak_sample]
coeffs        = np.polyfit(hw_vals, power_at_peak, deg=1)
alpha, beta   = coeffs
fit_line      = np.poly1d(coeffs)
ss_res = np.sum((power_at_peak - fit_line(hw_vals)) ** 2)
ss_tot = np.sum((power_at_peak - power_at_peak.mean()) ** 2)
r2 = 1 - ss_res / ss_tot


# ═════════════════════════════════════════════════════════════════════════════
# Plotting
# ═════════════════════════════════════════════════════════════════════════════
plt.rcParams.update({
    'figure.facecolor' : 'white',
    'axes.facecolor'   : 'white',
    'axes.grid'        : True,
    'grid.alpha'       : 0.35,
    'axes.spines.top'  : False,
    'axes.spines.right': False,
    'font.size'        : 10,
})


# ── Plot 1 — Mean traces + difference ────────────────────────────────────────
# What to look for:
#   The difference trace (bottom panel) should be flat (≈0) if no leakage.
#   Any spike in the difference trace pinpoints the leaky clock cycle.
fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
fig.suptitle("TVLA — Mean Traces and Difference Trace", fontweight='bold')

axes[0].plot(t_axis, mean_fixed,  color='#D85A30', lw=0.9,
             label=f'Fixed  (0x{fixed_val:02X})')
axes[0].set_ylabel("Voltage (V)")
axes[0].legend(loc='upper right')
axes[0].set_title("Fixed group — mean of all fixed traces")

axes[1].plot(t_axis, mean_random, color='#185FA5', lw=0.9, label='Random')
axes[1].set_ylabel("Voltage (V)")
axes[1].legend(loc='upper right')
axes[1].set_title("Random group — mean of all random traces")

axes[2].plot(t_axis, difference,  color='#0F6E56', lw=0.9, label='Fixed − Random')
axes[2].axhline(0, color='black', lw=0.5, linestyle='--')
axes[2].set_ylabel("ΔVoltage (V)")
axes[2].set_xlabel("Time (µs)")
axes[2].legend(loc='upper right')
axes[2].set_title("Difference trace — non-zero spikes = data-dependent leakage")

for ax in axes:
    ax.set_xlim(0, 10)
    for c in cycles:
        if c < n_samples:
            ax.axvline(t_axis[c], color='gray', lw=0.4, linestyle=':')

plt.tight_layout()
plt.savefig(os.path.join(PLOT_DIR, "1_mean_traces.png"), dpi=150)
plt.show()
print("[plot] Saved 1_mean_traces.png")


# ── Plot 2 — TVLA t-statistic ─────────────────────────────────────────────────
# What to look for:
#   Any sample where |t| > 4.5 is a confirmed leak.
#   The cycle (x-axis position) tells you WHICH instruction is leaking.
fig, ax = plt.subplots(figsize=(14, 5))
ax.plot(t_axis, t_stat, color='#534AB7', lw=0.9, label='t-statistic')
ax.axhline( T_THRESHOLD, color='#D85A30', lw=1.2, linestyle='--',
            label=f'+{T_THRESHOLD} threshold')
ax.axhline(-T_THRESHOLD, color='#D85A30', lw=1.2, linestyle='--',
            label=f'−{T_THRESHOLD} threshold')
ax.fill_between(t_axis,  t_stat,  T_THRESHOLD,
                where=(t_stat >  T_THRESHOLD), color='#D85A30', alpha=0.3,
                label='Leaky region')
ax.fill_between(t_axis,  t_stat, -T_THRESHOLD,
                where=(t_stat < -T_THRESHOLD), color='#D85A30', alpha=0.3)

for c in cycles:
    if c < n_samples:
        ax.axvline(t_axis[c], color='gray', lw=0.4, linestyle=':')

ax.set_xlabel("Time (µs)")
ax.set_ylabel("Welch t-statistic")
ax.set_title(
    f"TVLA — Fixed (0x{fixed_val:02X}) vs Random  "
    f"[N = {len(fixed_traces)} traces per group]  "
    + ('⚠  LEAKAGE DETECTED' if len(leaky_samples) else '✓  No leakage detected')
)
ax.legend(loc='upper right')
plt.tight_layout()
plt.savefig(os.path.join(PLOT_DIR, "2_tvla_tstat.png"), dpi=150)
plt.show()
print("[plot] Saved 2_tvla_tstat.png")


# ── Plot 3 — SNR ──────────────────────────────────────────────────────────────
# What to look for:
#   High SNR at a sample = that sample's power strongly separates
#   different input values. SNR > ~0.01 is worth investigating.
fig, ax = plt.subplots(figsize=(14, 4))
ax.plot(t_axis, snr_vals, color='#854F0B', lw=0.9)
ax.fill_between(t_axis, snr_vals, alpha=0.2, color='#854F0B')
for c in cycles:
    if c < n_samples:
        ax.axvline(t_axis[c], color='gray', lw=0.4, linestyle=':')
ax.set_xlabel("Time (µs)")
ax.set_ylabel("SNR")
ax.set_title(f"Signal-to-Noise Ratio per sample point  "
             f"(peak = {peak_snr:.4f} at cycle {peak_snr_cyc})")
plt.tight_layout()
plt.savefig(os.path.join(PLOT_DIR, "3_snr.png"), dpi=150)
plt.show()
print("[plot] Saved 3_snr.png")


# ── Plot 4 — HW correlation ───────────────────────────────────────────────────
# What to look for:
#   A correlation spike at a particular sample means power at that
#   point is linearly related to HW(input) — the textbook HW leakage model.
fig, ax = plt.subplots(figsize=(14, 4))
ax.plot(t_axis, hw_corr, color='#185FA5', lw=0.9)
ax.axhline(0, color='black', lw=0.5)
ax.fill_between(t_axis, hw_corr, alpha=0.15, color='#185FA5')
for c in cycles:
    if c < n_samples:
        ax.axvline(t_axis[c], color='gray', lw=0.4, linestyle=':')
ax.set_xlabel("Time (µs)")
ax.set_ylabel("Pearson r")
ax.set_title(f"Hamming Weight correlation with power  "
             f"(peak |r| = {peak_hw_corr:.4f} at cycle {peak_hw_cyc})")
plt.tight_layout()
plt.savefig(os.path.join(PLOT_DIR, "4_hw_correlation.png"), dpi=150)
plt.show()
print("[plot] Saved 4_hw_correlation.png")


# ── Plot 5 — HW scatter + regression fit ─────────────────────────────────────
# What to look for:
#   A tight, positive-slope regression means the HW model fits well.
#   R² close to 1.0 = strong linear leakage. R² close to 0 = noise dominates.
#   alpha (slope) is your leakage coefficient in V/bit.
hw_range = np.linspace(0, 8, 100)

fig, ax = plt.subplots(figsize=(8, 6))
ax.scatter(hw_vals, power_at_peak, alpha=0.3, s=8, color='#185FA5',
           label='Measured traces')
ax.plot(hw_range, fit_line(hw_range), color='#D85A30', lw=2,
        label=(f'Fit: P = {alpha:.4f}·HW(v) + {beta:.4f}\n'
               f'R² = {r2:.4f}'))
ax.set_xlabel("Hamming Weight  HW(input byte)")
ax.set_ylabel(f"Voltage at sample {peak_sample} (V)")
ax.set_title(f"HW leakage model fit  "
             f"(cycle {peak_sample // SAMPLES_PER_CYCLE})\n"
             f"α = {alpha:.4f} V/bit  —  "
             f"{'strong leakage' if r2 > 0.5 else 'weak / no leakage'}")
ax.legend()
plt.tight_layout()
plt.savefig(os.path.join(PLOT_DIR, "5_hw_scatter.png"), dpi=150)
plt.show()
print("[plot] Saved 5_hw_scatter.png")


# ── Plot 6 — Mean trace overlay by HW group ───────────────────────────────────
# What to look for:
#   Visible vertical separation between the HW=0, HW=4, HW=8 lines at any
#   clock cycle is direct visual proof of HW leakage at that cycle.
fig, ax = plt.subplots(figsize=(14, 5))
hw_groups = {0: '#D85A30', 4: '#534AB7', 8: '#0F6E56'}
for hw_target, col in hw_groups.items():
    mask = hw_vals == hw_target
    if mask.sum() == 0:
        continue
    group_mean = random_traces[mask].mean(axis=0)
    ax.plot(t_axis, group_mean, color=col, lw=1.1,
            label=f'HW = {hw_target}  (n = {mask.sum()})')

for c in cycles:
    if c < n_samples:
        ax.axvline(t_axis[c], color='gray', lw=0.4, linestyle=':')

ax.set_xlabel("Time (µs)")
ax.set_ylabel("Voltage (V)")
ax.set_title("Mean power trace grouped by Hamming Weight of input\n"
             "Vertical separation between lines = HW leakage")
ax.legend()
plt.tight_layout()
plt.savefig(os.path.join(PLOT_DIR, "6_hw_overlay.png"), dpi=150)
plt.show()
print("[plot] Saved 6_hw_overlay.png")


# ── Summary printout ──────────────────────────────────────────────────────────
print("\n" + "═" * 60)
print("  TVLA SUMMARY")
print("═" * 60)
print(f"  Traces per group       : {len(fixed_traces)}")
print(f"  Samples per trace      : {n_samples}")
print(f"  Samples per cycle      : {SAMPLES_PER_CYCLE}")
print(f"  Fixed value            : 0x{fixed_val:02X}")
print(f"  t-threshold            : {T_THRESHOLD}")
print(f"  Leaky sample points    : {len(leaky_samples)}")
if len(leaky_samples):
    print(f"  Leaky clock cycles     : {leaky_cycles.tolist()}")
    print(f"  Max |t-statistic|      : {np.max(np.abs(t_stat)):.2f}")
print(f"  Peak SNR               : {peak_snr:.4f}  (cycle {peak_snr_cyc})")
print(f"  Peak |HW correlation|  : {peak_hw_corr:.4f}  (cycle {peak_hw_cyc})")
print(f"  HW model α  (slope)    : {alpha:.6f}  V/bit")
print(f"  HW model β  (offset)   : {beta:.6f}  V")
print(f"  HW model R²            : {r2:.4f}")
print("═" * 60)
print(f"\nAll plots saved to ./{PLOT_DIR}/")
