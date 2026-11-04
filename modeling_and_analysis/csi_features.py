"""Exploratory CSI window features; NumPy only, no occupancy classifier."""

import numpy as np


def _median(values):
    values = np.asarray(values)
    good = values[np.isfinite(values)]
    return float(np.median(good)) if good.size else float('nan')


def _shape_features(x):
    centered = x - np.mean(x, axis=0)
    std = np.std(x, axis=0)
    active = std > 1e-10
    if not np.any(active):
        return 0.0, 0.0
    z = centered[:, active] / std[active]
    singular = np.linalg.svd(z, compute_uv=False)
    pca_fraction = float(singular[0] ** 2 / np.sum(singular ** 2))
    if z.shape[1] < 2:
        return float('nan'), pca_fraction
    correlation = (z.T @ z) / len(z)
    pairs = np.triu_indices(z.shape[1], 1)
    return float(np.mean(np.abs(correlation[pairs]))), pca_fraction


def _periodicity(t, x, band, min_cycles):
    """Sinusoid fits at actual timestamps, after removing a linear trend.

    Scores are fractions of detrended variance explained, not a calibrated PSD.
    Aggregate across informative bins by the median, rather than picking one bin.
    """
    span = t[-1] - t[0]
    lower = max(band[0], min_cycles / span)
    if lower >= band[1]:
        return float('nan'), float('nan')
    t = t - t[0]
    trend = np.column_stack([np.ones(len(t)), t])
    residual = x - trend @ np.linalg.lstsq(trend, x, rcond=None)[0]
    energy = np.sum(residual ** 2, axis=0)
    usable = energy > 1e-10
    if not np.any(usable):
        return float('nan'), 0.0
    residual = residual[:, usable]
    energy = energy[usable]
    frequencies = np.linspace(lower, band[1], 160)
    scores = []
    for frequency in frequencies:
        basis = np.column_stack([np.sin(2 * np.pi * frequency * t),
                                 np.cos(2 * np.pi * frequency * t)])
        # Residualize the sinusoid too, to compare against a trend-only model.
        basis -= trend @ np.linalg.lstsq(trend, basis, rcond=None)[0]
        fitted = basis @ np.linalg.lstsq(basis, residual, rcond=None)[0]
        scores.append(np.median(np.clip(np.sum(fitted ** 2, axis=0) / energy, 0, 1)))
    best = int(np.argmax(scores))
    return float(frequencies[best]), float(scores[best])


def extract_features(time_s, channel, bins=None, window_seconds=30.0,
                     hop_seconds=5.0, min_packets=12, max_gap_seconds=2.0,
                     periodic_band=(0.1, 0.5), min_cycles=3,
                     start_s=None, end_s=None):
    """Return one dict per complete window. Inadequate windows remain flagged.

    Pair indices retain original buffer positions. Invalid samples must already
    be NaN. Phase is uncalibrated; phase features are exploratory diagnostics.
    Explicit start/end bounds support rolling buffers without shifting the
    window grid to the first packet that happens to survive an upload gap.
    """
    t = np.asarray(time_s, dtype=float)
    h = np.asarray(channel, dtype=complex)
    if t.ndim != 1 or h.ndim != 2 or h.shape[0] != len(t):
        raise ValueError('Expected time (packets,) and channel (packets, bins).')
    if ((len(t) < 2 and (start_s is None or end_s is None)) or
            not np.all(np.isfinite(t)) or np.any(np.diff(t) < 0)):
        raise ValueError('At least two finite, nondecreasing timestamps required.')
    if window_seconds <= 0 or hop_seconds <= 0 or max_gap_seconds <= 0:
        raise ValueError('Window, hop, and maximum gap must be positive.')
    if not 0 < periodic_band[0] < periodic_band[1] or min_packets < 3 or min_cycles < 1:
        raise ValueError('Invalid periodic band, packet count, or cycle count.')
    if bins is not None:
        h = h[:, bins]
    names = ['amplitude_mean', 'amplitude_std_median', 'amplitude_mad_median',
             'amplitude_cv_median', 'amplitude_step_median',
             'amplitude_change_rate_median', 'normalized_std_median',
             'normalized_step_median', 'subcarrier_abs_correlation',
             'pca1_variance_fraction', 'phase_step_abs_median_rad',
             'relative_phase_step_abs_median_rad', 'periodic_peak_hz',
             'periodic_explained_fraction']
    rows = []
    start = float(t[0]) if start_s is None else float(start_s)
    end = float(t[-1]) if end_s is None else float(end_s)
    if not np.isfinite(start) or not np.isfinite(end) or end < start:
        raise ValueError('Window bounds must be finite and nondecreasing.')
    while start + window_seconds <= end + 1e-9:
        stop = start + window_seconds
        mask = (t >= start) & (t < stop)
        tw, hw = t[mask], h[mask]
        row = dict(window_start_s=start, window_end_s=stop,
                   window_center_s=(start + stop) / 2, packet_count=len(tw),
                   bin_count=0, imputed_fraction=float('nan'),
                   packet_rate_hz=0.0, max_gap_s=window_seconds,
                   quality_ok=False, periodicity_ok=False)
        row.update({name: float('nan') for name in names})
        rows.append(row)
        start += hop_seconds
        if len(tw) < min_packets:
            continue
        gaps = np.diff(tw)
        positive = gaps > 0
        row['packet_rate_hz'] = float((len(tw) - 1) / (tw[-1] - tw[0])) if tw[-1] > tw[0] else 0.0
        # Include unobserved edges of the requested window in the gap metric.
        row['max_gap_s'] = float(max(np.max(gaps), tw[0] - (stop-window_seconds), stop-tw[-1]))
        amplitude = np.abs(hw)
        good = (np.mean(np.isfinite(amplitude), axis=0) >= 0.8)
        good &= np.any(np.isfinite(amplitude) & (amplitude > 0), axis=0)
        if not np.any(good):
            continue
        hw, amplitude = hw[:, good], amplitude[:, good]
        row['bin_count'] = amplitude.shape[1]
        row['imputed_fraction'] = float(np.mean(~np.isfinite(amplitude)))
        medians = np.nanmedian(amplitude, axis=0)
        spread = np.nanstd(amplitude, axis=0)
        row['amplitude_mean'] = float(np.nanmean(amplitude))
        row['amplitude_std_median'] = _median(spread)
        row['amplitude_mad_median'] = _median(np.nanmedian(np.abs(amplitude-medians), axis=0))
        means = np.nanmean(amplitude, axis=0)
        row['amplitude_cv_median'] = _median(np.divide(spread, means, out=np.full_like(means, np.nan), where=means > 1e-10))
        # Normalize per packet across bins; keep raw features as well.
        scale = np.nanmean(amplitude, axis=1, keepdims=True)
        normalized = np.divide(amplitude, scale, out=np.full_like(amplitude, np.nan), where=scale > 1e-10)
        row['normalized_std_median'] = _median(np.nanstd(normalized, axis=0))
        adjacent = positive & (gaps <= max_gap_seconds)
        if np.any(adjacent):
            steps = np.abs(np.diff(amplitude, axis=0))[adjacent]
            row['amplitude_step_median'] = _median(steps)
            row['amplitude_change_rate_median'] = _median(steps / gaps[adjacent, None])
            row['normalized_step_median'] = _median(np.abs(np.diff(normalized, axis=0))[adjacent])
            # Circular increments avoid interpreting a +/-pi crossing as a jump.
            ph = np.angle(hw)
            ph[(amplitude == 0) | ~np.isfinite(amplitude)] = np.nan
            delta = np.angle(np.exp(1j * np.diff(ph, axis=0)))[adjacent]
            row['phase_step_abs_median_rad'] = _median(np.abs(delta))
            # Remove the circular common phase increment per packet pair.
            # This is not full phase calibration or a two-antenna CSI ratio.
            count = np.sum(np.isfinite(delta), axis=1)
            common = np.angle(np.nansum(np.exp(1j * delta), axis=1))
            relative = np.angle(np.exp(1j * (delta - common[:, None])))
            relative[count < 2] = np.nan
            row['relative_phase_step_abs_median_rad'] = _median(np.abs(relative))
        # Multivariate/spectral calculations use median imputation, reported above.
        fill = np.nanmedian(normalized, axis=0)
        usable = np.isfinite(fill)
        x = normalized[:, usable]
        if x.shape[1] == 0:
            continue
        x = np.where(np.isfinite(x), x, fill[usable])
        corr, pca = _shape_features(x)
        row['subcarrier_abs_correlation'] = corr
        row['pca1_variance_fraction'] = pca
        row['quality_ok'] = bool(row['max_gap_s'] <= max_gap_seconds)
        # A rate guard is necessary but does not eliminate irregular-sampling aliases.
        if row['quality_ok'] and row['packet_rate_hz'] > 2 * periodic_band[1]:
            frequency, score = _periodicity(tw, x, periodic_band, min_cycles)
            row['periodic_peak_hz'] = frequency
            row['periodic_explained_fraction'] = score
            row['periodicity_ok'] = bool(np.isfinite(frequency))
    return rows
