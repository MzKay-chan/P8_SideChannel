"""
TVLA analysis — multi-test edition.

Usage
-----
    python tvla_analysis.backup.py                      # analyse every test found
    python tvla_analysis.backup.py mov                  # one test
    python tvla_analysis.backup.py mov eor and add      # several specific tests

Auto-discovery: any folder named  tvla_traces_<name>/  containing a full dataset
(fixed_traces.npy, random_traces.npy, random_vals.npy, fixed_val.npy) is treated
as a runnable test. Missing folders are skipped with a warning.

Outputs
-------
    tvla_plots_<name>/   — six per-test plots (means, t-stat, SNR, HW corr, HW
                            scatter, HW overlay) and a per-test summary print
    tvla_summary/        — cross-test comparison bar chart + summary.json table

Tweak the constants in CONFIGURATION below to change behaviour.
"""

import os
import sys
import glob
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats

# ── CONFIGURATION ────────────────────────────────────────────────────────────
T_THRESHOLD          = 4.5                 # standard TVLA pass/fail threshold
SAMPLE_RATE          = 100e6               # Hz  (100 MHz AD2 sample rate)
CLOCK_FREQ           = 1e6                 # Hz  (1 MHz ATmega clock)
SAMPLES_PER_CYCLE    = int(SAMPLE_RATE / CLOCK_FREQ)   # 100 samples per clock cycle

# Sample-offset between the scope trigger edge and the first cycle of OP_ASM.
# With direct port writes (sbi/cbi) the trigger fires 1 cycle before OP_ASM,
# so this is ~ SAMPLES_PER_CYCLE. Tweak by eyeballing one trace if needed.
CYCLE_OFFSET_SAMPLES = SAMPLES_PER_CYCLE

# Re-alignment on top of the scope's hardware trigger. Set to 0 to disable.
# When >0, looks for the first rising edge in each trace within this window
# using a GLOBAL threshold (median of trace midpoints) rather than per-trace.
ALIGN_SEARCH_WINDOW  = 200

# Set True to pop each plot up interactively (blocks until you close it).
# Default False so batch runs over many tests don't pause for a click.
SHOW_PLOTS           = False

SUMMARY_DIR          = "tvla_summary"
REQUIRED_FILES       = ["fixed_traces.npy", "random_traces.npy",
                        "random_vals.npy",  "fixed_val.npy"]


# ── Helpers ──────────────────────────────────────────────────────────────────
def time_axis(n_samples):
    return np.arange(n_samples) / SAMPLE_RATE * 16e6 #Remeber to change this value when changing the clock frequency


def cycle_boundaries(n_samples):
    return np.arange(CYCLE_OFFSET_SAMPLES, n_samples, SAMPLES_PER_CYCLE)


def sample_to_cycle(sample_idx):
    return (np.asarray(sample_idx) - CYCLE_OFFSET_SAMPLES) // SAMPLES_PER_CYCLE


def align_traces(traces, search_window=ALIGN_SEARCH_WINDOW):
    """
    Re-align traces on top of the scope's hardware trigger by finding the first
    rising edge in the power signal within `search_window` samples.

    Uses a single GLOBAL threshold (median of per-trace midpoints) so traces
    with different DC offsets all cross at the same absolute voltage level.
    Set search_window <= 0 to no-op and trust the scope's trigger.
    """
    if search_window <= 0:
        return np.asarray(traces, dtype=np.float32)

    windows   = traces[:, :search_window]
    midpoints = (windows.max(axis=1) + windows.min(axis=1)) / 2.0
    threshold = float(np.median(midpoints))

    edges = np.zeros(len(traces), dtype=np.int64)
    for i, tr in enumerate(traces):
        w = tr[:search_window]
        crossings = np.where((w[:-1] < threshold) & (w[1:] >= threshold))[0]
        edges[i] = crossings[0] if len(crossings) > 0 else 0

    aligned_len = traces.shape[1] - int(edges.max())
    aligned = np.empty((len(traces), aligned_len), dtype=np.float32)
    for i, tr in enumerate(traces):
        aligned[i] = tr[edges[i]:edges[i] + aligned_len]
    return aligned


def welch_ttest(fixed, random_):
    t_stat, _ = stats.ttest_ind(fixed, random_, axis=0, equal_var=False)
    return t_stat


def hw_correlation(traces, hw_vals):
    """
    Pearson correlation between Hamming-Weight(input) and power at each sample.
    Vectorised — equivalent to the per-sample np.corrcoef loop but ~100× faster.
    """
    hw_c  = hw_vals - hw_vals.mean()
    tr_c  = traces - traces.mean(axis=0)
    num   = (hw_c[:, None] * tr_c).sum(axis=0)
    denom = np.sqrt((hw_c ** 2).sum() * (tr_c ** 2).sum(axis=0))
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(denom > 0, num / denom, 0.0)


def compute_snr(traces, vals):
    """
    SNR per sample. Uses unbiased (sample) variance with ddof=1 throughout.
    Single-sample groups are skipped with a warning.
    """
    unique_vals = np.unique(vals)
    group_means = []
    group_vars  = []
    skipped     = 0
    for v in unique_vals:
        group = traces[vals == v]
        if len(group) < 2:
            skipped += 1
            continue
        group_means.append(group.mean(axis=0))
        group_vars.append(group.var(axis=0, ddof=1))
    if skipped:
        print(f"  [snr] skipped {skipped}/{len(unique_vals)} groups (<2 traces each)")

    group_means = np.array(group_means)
    group_vars  = np.array(group_vars)
    signal      = group_means.var(axis=0, ddof=1)
    noise       = group_vars.mean(axis=0)
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(noise > 0, signal / noise, 0.0)


def _save(fig, plot_dir, fname):
    out = os.path.join(plot_dir, fname)
    fig.savefig(out, dpi=150)
    if SHOW_PLOTS:
        plt.show()
    plt.close(fig)
    print(f"  [plot] {out}")


# ── Discovery ────────────────────────────────────────────────────────────────
def discover_tests():
    """Return sorted list of test names with a complete dataset on disk."""
    tests = []
    for folder in sorted(glob.glob("tvla_traces_*")):
        name = folder[len("tvla_traces_"):]
        if not name:
            continue
        if all(os.path.exists(os.path.join(folder, f)) for f in REQUIRED_FILES):
            tests.append(name)
        else:
            print(f"  [skip] {folder}: missing one or more of {REQUIRED_FILES}")
    return tests


# ── Per-test analysis ────────────────────────────────────────────────────────
def analyze_test(test_name):
    """Run the full pipeline on one test. Returns summary dict, or None on failure."""
    save_dir = f"tvla_traces_{test_name}"
    plot_dir = f"tvla_plots_{test_name}"

    for f in REQUIRED_FILES:
        path = os.path.join(save_dir, f)
        if not os.path.exists(path):
            print(f"  [error] missing {path} — skipping")
            return None

    os.makedirs(plot_dir, exist_ok=True)

    # ── Load ──
    fixed_traces  = np.load(os.path.join(save_dir, "fixed_traces.npy"))
    random_traces = np.load(os.path.join(save_dir, "random_traces.npy"))
    random_vals   = np.load(os.path.join(save_dir, "random_vals.npy"))
    fixed_val     = int(np.load(os.path.join(save_dir, "fixed_val.npy"))[0])

    print(f"  fixed_traces  : {fixed_traces.shape}")
    print(f"  random_traces : {random_traces.shape}")
    print(f"  random_vals   : {random_vals.shape}")
    print(f"  fixed value   : 0x{fixed_val:02X}")

    # ── Step 1 — alignment ──
    if ALIGN_SEARCH_WINDOW > 0:
        print(f"  [align] global-threshold realign, window={ALIGN_SEARCH_WINDOW}")
    else:
        print(f"  [align] disabled — trusting scope hardware trigger")
    fixed_traces  = align_traces(fixed_traces)
    random_traces = align_traces(random_traces)
    min_len       = min(fixed_traces.shape[1], random_traces.shape[1])
    fixed_traces  = fixed_traces[:,  :min_len]
    random_traces = random_traces[:, :min_len]

    n_samples = min_len
    t_axis    = time_axis(n_samples)
    cycles    = cycle_boundaries(n_samples)

    # ── Step 2 — means / difference ──
    mean_fixed  = fixed_traces.mean(axis=0)
    mean_random = random_traces.mean(axis=0)
    difference  = mean_fixed - mean_random

    # ── Step 3 — Welch t-test ──
    t_stat        = welch_ttest(fixed_traces, random_traces)
    leaky_samples = np.where(np.abs(t_stat) > T_THRESHOLD)[0]
    leaky_cycles  = np.unique(sample_to_cycle(leaky_samples))
    peak_t        = float(np.max(np.abs(t_stat)))
    peak_t_sample = int(np.argmax(np.abs(t_stat)))
    peak_t_cycle  = int(sample_to_cycle(peak_t_sample))

    if len(leaky_samples):
        print(f"  [tvla] LEAKAGE — {len(leaky_samples)} samples > {T_THRESHOLD}, "
              f"peak |t|={peak_t:.2f} at sample {peak_t_sample} (cycle {peak_t_cycle})")
    else:
        print(f"  [tvla] no leakage — peak |t|={peak_t:.2f} (< {T_THRESHOLD})")

    # ── Step 4 — SNR ──
    snr_vals     = compute_snr(random_traces, random_vals)
    peak_snr     = float(snr_vals.max())
    peak_snr_cyc = int(sample_to_cycle(snr_vals.argmax()))
    print(f"  [snr] peak SNR={peak_snr:.4f} at cycle {peak_snr_cyc}")

    # ── Step 5 — HW correlation ──
    hw_vals      = np.array([bin(v).count('1') for v in random_vals], dtype=np.float32)
    hw_corr      = hw_correlation(random_traces, hw_vals)
    peak_hw_corr = float(np.max(np.abs(hw_corr)))
    peak_hw_cyc  = int(sample_to_cycle(np.argmax(np.abs(hw_corr))))
    print(f"  [hw]  peak |HW r|={peak_hw_corr:.4f} at cycle {peak_hw_cyc}")

    # ── Step 6 — HW linear regression at peak sample ──
    peak_sample   = int(np.argmax(np.abs(hw_corr)))
    power_at_peak = random_traces[:, peak_sample]
    coeffs        = np.polyfit(hw_vals, power_at_peak, deg=1)
    alpha, beta   = float(coeffs[0]), float(coeffs[1])
    fit_line      = np.poly1d(coeffs)
    ss_res = float(np.sum((power_at_peak - fit_line(hw_vals)) ** 2))
    ss_tot = float(np.sum((power_at_peak - power_at_peak.mean()) ** 2))
    r2     = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Plots
    # ─────────────────────────────────────────────────────────────────────────
    title_suffix = f"  [{test_name}]"

    # Plot 1 — Mean traces + difference
    fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
    fig.suptitle("TVLA — Mean Traces and Difference Trace" + title_suffix,
                 fontweight='bold')
    axes[0].plot(t_axis, mean_fixed,  color='#D85A30', lw=0.9,
                 label=f'Fixed  (0x{fixed_val:02X})')
    axes[0].set_ylabel("Voltage (V)")
    axes[0].legend(loc='upper right')
    axes[0].set_title("Fixed group — mean of all fixed traces")
    axes[1].plot(t_axis, mean_random, color='#185FA5', lw=0.9, label='Random')
    axes[1].set_ylabel("Voltage (V)")
    axes[1].legend(loc='upper right')
    axes[1].set_title("Random group — This test uses 0xFF for all random traces")
    axes[2].plot(t_axis, difference,  color='#0F6E56', lw=0.9, label='Fixed − Random')
    axes[2].axhline(0, color='black', lw=0.5, linestyle='--')
    axes[2].set_ylabel("ΔVoltage (V)")
    axes[2].set_xlabel("Time (µs)")
    axes[2].legend(loc='upper right')
    axes[2].set_title("Difference trace — non-zero spikes = data-dependent leakage")
    for ax in axes:
        ax.set_xlim(t_axis[0], t_axis[-1])
        for c in cycles:
            if c < n_samples:
                ax.axvline(t_axis[c], color='gray', lw=0.4, linestyle=':')
    plt.tight_layout()
    _save(fig, plot_dir, "1_mean_traces.png")

    # Plot 2 — TVLA t-statistic
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(t_axis, t_stat, color='#534AB7', lw=0.9, label='t-statistic')
    ax.axhline( T_THRESHOLD, color='#D85A30', lw=1.2, linestyle='--',
                label=f'+{T_THRESHOLD} threshold')
    ax.axhline(-T_THRESHOLD, color='#D85A30', lw=1.2, linestyle='--',
                label=f'−{T_THRESHOLD} threshold')
    ax.fill_between(t_axis, t_stat,  T_THRESHOLD,
                    where=(t_stat >  T_THRESHOLD), color='#D85A30', alpha=0.3,
                    label='Leaky region')
    ax.fill_between(t_axis, t_stat, -T_THRESHOLD,
                    where=(t_stat < -T_THRESHOLD), color='#D85A30', alpha=0.3)
    for c in cycles:
        if c < n_samples:
            ax.axvline(t_axis[c], color='gray', lw=0.4, linestyle=':')
    ax.set_xlabel("Time (µs)")
    ax.set_ylabel("Welch t-statistic")
    verdict = '⚠  LEAKAGE DETECTED' if len(leaky_samples) else '✓  No leakage detected'
    ax.set_title(f"TVLA — Fixed (0x{fixed_val:02X}) vs Random  "
                 f"[N = {len(fixed_traces)}]" + title_suffix + f"  {verdict}")
    ax.legend(loc='upper right')
    plt.tight_layout()
    _save(fig, plot_dir, "2_tvla_tstat.png")

    # Plot 3 — SNR
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(t_axis, snr_vals, color='#854F0B', lw=0.9)
    ax.fill_between(t_axis, snr_vals, alpha=0.2, color='#854F0B')
    for c in cycles:
        if c < n_samples:
            ax.axvline(t_axis[c], color='gray', lw=0.4, linestyle=':')
    ax.set_xlabel("Time (µs)")
    ax.set_ylabel("SNR")
    ax.set_title(f"SNR per sample  (peak = {peak_snr:.4f} at cycle {peak_snr_cyc})"
                 + title_suffix)
    plt.tight_layout()
    _save(fig, plot_dir, "3_snr.png")

    # Plot 4 — HW correlation
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(t_axis, hw_corr, color='#185FA5', lw=0.9)
    ax.axhline(0, color='black', lw=0.5)
    ax.fill_between(t_axis, hw_corr, alpha=0.15, color='#185FA5')
    for c in cycles:
        if c < n_samples:
            ax.axvline(t_axis[c], color='gray', lw=0.4, linestyle=':')
    ax.set_xlabel("Time (µs)")
    ax.set_ylabel("Pearson r")
    ax.set_title(f"HW correlation with power  "
                 f"(peak |r| = {peak_hw_corr:.4f} at cycle {peak_hw_cyc})"
                 + title_suffix)
    plt.tight_layout()
    _save(fig, plot_dir, "4_hw_correlation.png")

    # Plot 5 — HW scatter + regression fit
    hw_range = np.linspace(0, 8, 100)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(hw_vals, power_at_peak, alpha=0.3, s=8, color='#185FA5',
               label='Measured traces')
    ax.plot(hw_range, fit_line(hw_range), color='#D85A30', lw=2,
            label=f'Fit: P = {alpha:.4f}·HW(v) + {beta:.4f}\nR² = {r2:.4f}')
    ax.set_xlabel("Hamming Weight  HW(input byte)")
    ax.set_ylabel(f"Voltage at sample {peak_sample} (V)")
    leak_label = 'strong leakage' if r2 > 0.5 else 'weak / no leakage'
    ax.set_title(f"HW leakage model fit  (cycle {int(sample_to_cycle(peak_sample))})"
                 + title_suffix + f"\nα = {alpha:.4f} V/bit  —  {leak_label}")
    ax.legend()
    plt.tight_layout()
    _save(fig, plot_dir, "5_hw_scatter.png")

    # Plot 6 — Mean trace overlay by HW group
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
    ax.set_title("Mean power trace grouped by Hamming Weight of input"
                 + title_suffix +
                 "\nVertical separation between lines = HW leakage")
    ax.legend()
    plt.tight_layout()
    _save(fig, plot_dir, "6_hw_overlay.png")

    return {
        'name'            : test_name,
        'n_traces'        : int(len(fixed_traces)),
        'n_samples'       : int(n_samples),
        'fixed_val'       : fixed_val,
        'leaky_samples'   : int(len(leaky_samples)),
        'leaky_cycles'    : leaky_cycles.tolist(),
        'peak_t'          : peak_t,
        'peak_t_sample'   : peak_t_sample,
        'peak_t_cycle'    : peak_t_cycle,
        'peak_snr'        : peak_snr,
        'peak_snr_cycle'  : peak_snr_cyc,
        'peak_hw_corr'    : peak_hw_corr,
        'peak_hw_cycle'   : peak_hw_cyc,
        'alpha'           : alpha,
        'beta'            : beta,
        'r2'              : r2,
    }


# ── Cross-test comparison ────────────────────────────────────────────────────
def plot_comparison(summaries, out_dir=SUMMARY_DIR):
    """Bar charts comparing leakage metrics across all analysed tests."""
    if len(summaries) < 1:
        return
    os.makedirs(out_dir, exist_ok=True)

    sums  = sorted(summaries, key=lambda s: s['peak_t'])
    names = [s['name']         for s in sums]
    t_pk  = [s['peak_t']       for s in sums]
    snr   = [s['peak_snr']     for s in sums]
    hw    = [s['peak_hw_corr'] for s in sums]
    r2    = [s['r2']           for s in sums]

    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    fig.suptitle(f"Leakage comparison — {len(sums)} test variants",
                 fontweight='bold')

    ax = axes[0, 0]
    colors = ['#0F6E56' if t <= T_THRESHOLD else '#D85A30' for t in t_pk]
    ax.barh(names, t_pk, color=colors)
    ax.axvline(T_THRESHOLD, color='black', linestyle='--', lw=1,
               label=f'TVLA threshold = {T_THRESHOLD}')
    ax.set_xlabel("peak |t-statistic|")
    ax.set_title("Welch t-test peak (TVLA)")
    ax.legend(loc='lower right')

    ax = axes[0, 1]
    ax.barh(names, snr, color='#854F0B')
    ax.set_xlabel("peak SNR")
    ax.set_title("Signal-to-Noise Ratio peak")

    ax = axes[1, 0]
    ax.barh(names, hw, color='#185FA5')
    ax.set_xlabel("peak |Pearson r|")
    ax.set_title("Hamming-Weight correlation peak")

    ax = axes[1, 1]
    ax.barh(names, r2, color='#534AB7')
    ax.set_xlabel("R²")
    ax.set_title("HW linear-model goodness of fit")

    plt.tight_layout()
    out_png = os.path.join(out_dir, "comparison.png")
    fig.savefig(out_png, dpi=150)
    if SHOW_PLOTS:
        plt.show()
    plt.close(fig)
    print(f"  [plot] {out_png}")

    # JSON dump for later re-processing
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(sums, f, indent=2)

    # Text table — most leaky first
    print()
    print("═" * 80)
    print(f"  {'Test':<10} {'peak |t|':>10} {'peak SNR':>10} {'peak |r|':>10} "
          f"{'R²':>8}   Verdict")
    print("─" * 80)
    for s in reversed(sums):
        verdict = "⚠ LEAK" if s['peak_t'] > T_THRESHOLD else "  ok  "
        print(f"  {s['name']:<10} {s['peak_t']:>10.2f} {s['peak_snr']:>10.4f} "
              f"{s['peak_hw_corr']:>10.4f} {s['r2']:>8.4f}   {verdict}")
    print("═" * 80)


# ── Plot styling ─────────────────────────────────────────────────────────────
plt.rcParams.update({
    'figure.facecolor' : 'white',
    'axes.facecolor'   : 'white',
    'axes.grid'        : True,
    'grid.alpha'       : 0.35,
    'axes.spines.top'  : False,
    'axes.spines.right': False,
    'font.size'        : 10,
})


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    requested = sys.argv[1:]
    available = discover_tests()

    if not available:
        print("No tvla_traces_<name>/ folders found in the current directory.")
        print("Run tvla.py first to capture traces.")
        sys.exit(1)

    if requested:
        tests   = [t for t in requested if t in available]
        missing = sorted(set(requested) - set(available))
        if missing:
            print(f"  [warn] requested but no data: {missing}")
        if not tests:
            print("  [error] none of the requested tests have data — exiting")
            sys.exit(1)
    else:
        tests = available
        print(f"[discover] {len(tests)} tests with data: {tests}")

    summaries = []
    for t in tests:
        print(f"\n══════════════════════════════════════════════════════════════")
        print(f"  Analysing: {t}")
        print(f"══════════════════════════════════════════════════════════════")
        try:
            s = analyze_test(t)
            if s is not None:
                summaries.append(s)
        except Exception as e:
            print(f"  [error] {t} failed: {type(e).__name__}: {e}")

    if summaries:
        print(f"\n══════════════════════════════════════════════════════════════")
        print(f"  Cross-test comparison ({len(summaries)} tests)")
        print(f"══════════════════════════════════════════════════════════════")
        plot_comparison(summaries)
