"""Causal feature tables, interval annotations, and explicit leakage-safe splits."""
from pathlib import Path
import csv
import json

import numpy as np
import pandas as pd

from csi_features import extract_features


MOTION_FEATURES = [
    'amplitude_mean', 'amplitude_std_median', 'amplitude_mad_median',
    'amplitude_cv_median', 'amplitude_step_median', 'amplitude_change_rate_median',
    'normalized_std_median', 'normalized_step_median',
    'subcarrier_abs_correlation', 'pca1_variance_fraction',
]
PHASE_FEATURES = ['phase_step_abs_median_rad', 'relative_phase_step_abs_median_rad']
SLOW_FEATURES = ['slow_periodic_peak_hz', 'slow_periodic_explained_fraction']
ALLOWED_FEATURES = MOTION_FEATURES + PHASE_FEATURES + SLOW_FEATURES
FAST_DEFAULTS = dict(window_seconds=5.0, hop_seconds=1.0, min_packets=12,
                     max_gap_seconds=2.0)
SLOW_DEFAULTS = dict(window_seconds=30.0, hop_seconds=5.0, min_packets=12,
                     max_gap_seconds=2.0)


def read_capture(path):
    """Decode this example's CSI; reject mixed source/channel/format captures."""
    records, malformed = [], 0
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        for row in csv.DictReader(stream):
            if row.get('type') != 'CSI_DATA':
                continue
            try:
                values = json.loads(row['data'])
                if not isinstance(values, list) or not all(type(v) is int for v in values):
                    raise ValueError('Noninteger data')
                if len(values) < 2 or len(values) % 2 or len(values) != int(row['len']):
                    raise ValueError('Bad length')
                collector_clock = 'timestamp_us' in row
                stamp = int(row['timestamp_us'] if collector_clock else row['local_timestamp'])
                invalid = int(row['first_word'])
                # Firmware prints the uint32 microsecond counter with %d, so
                # valid counters above INT32_MAX may appear as signed negatives.
                valid_stamp = (0 <= stamp < 2**63 if collector_clock
                               else -(2**31) <= stamp < 2**32)
                if not valid_stamp or invalid not in (0, 1):
                    raise ValueError('Bad metadata')
                if not collector_clock:
                    stamp = stamp % (2**32)
                group = (row.get('mac'), row.get('channel'), row.get('sig_mode', row.get('rx_format')),
                         row.get('bandwidth'), len(values))
                records.append((stamp, invalid, values, group, collector_clock))
            except (ValueError, KeyError, TypeError):
                malformed += 1
    if len(records) < 2:
        raise ValueError(f'{path}: fewer than two valid packets')
    if len({r[3] for r in records}) != 1:
        raise ValueError(f'{path}: multiple links/channels/formats; split into separate captures')
    if len({r[4] for r in records}) != 1:
        raise ValueError('Mixed collector and driver timestamp clocks; split captures first')
    stamps = np.array([r[0] for r in records], dtype=np.int64)
    delta = np.diff(stamps)
    if not records[0][4]:
        delta = np.where(delta < -(2**31), delta + 2**32, delta)
    if np.any(delta < 0):
        raise ValueError(f'{path}: clock reset/out-of-order packets; split sessions first')
    time = np.r_[0, np.cumsum(delta)] / 1e6
    raw = np.asarray([r[2] for r in records], dtype=float)
    channel = raw[:, 1::2] + 1j * raw[:, 0::2]
    channel[np.array([bool(r[1]) for r in records]), :2] = complex(np.nan, np.nan)
    timestamps = [int(stamps[0])]
    for step in delta:
        timestamps.append(timestamps[-1] + int(step))
    metadata = dict(sample_timestamps_us=timestamps,
                    source_mac=records[0][3][0], channel=records[0][3][1],
                    format=str(records[0][3][2:]), malformed_packets=malformed)
    return time, channel, metadata


def _bool(value):
    return str(value).strip().lower() in ('true', '1', 'yes')


def load_annotations(path, kind='labels'):
    columns = (['session_id', 'start_s', 'end_s', 'person_count', 'activity', 'notes']
               if kind == 'labels' else ['session_id', 'time_s', 'event', 'notes'])
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(path, keep_default_na=False)
    if not set(columns).issubset(frame.columns):
        raise ValueError(f'{path}: expected columns {columns}')
    for col in (['start_s', 'end_s'] if kind == 'labels' else ['time_s']):
        frame[col] = pd.to_numeric(frame[col], errors='raise')
        if not np.isfinite(frame[col]).all() or (frame[col] < 0).any():
            raise ValueError('Annotation times must be finite and nonnegative')
    if kind == 'labels':
        frame['person_count'] = pd.to_numeric(frame['person_count'].replace('', np.nan), errors='raise')
        count = frame.person_count.dropna()
        if (count < 0).any() or (count % 1 != 0).any():
            raise ValueError('Person counts must be nonnegative integers or blank')
        if (frame.end_s <= frame.start_s).any():
            raise ValueError('Label intervals must have positive duration')
        for _, group in frame.groupby('session_id'):
            group = group.sort_values('start_s')
            if len(group) > 1 and np.any(group.start_s.to_numpy()[1:] < group.end_s.to_numpy()[:-1]):
                raise ValueError('Overlapping label intervals within a session')
    return frame


def attach_labels(frame, labels):
    """Only label a window when its entire raw dependency interval is covered."""
    out = frame.copy()
    out['person_count'] = np.nan
    out['presence'] = np.nan
    out['count_class'] = np.nan
    out['activity'] = ''
    out['label_status'] = 'unlabeled'
    for i, row in out.iterrows():
        intervals = labels[labels.session_id == row.session_id]
        hit = intervals[(intervals.start_s <= row.feature_start_s) & (intervals.end_s >= row.window_end_s)]
        if len(hit) == 1:
            item = hit.iloc[0]
            out.at[i, 'activity'] = item.activity
            if pd.notna(item.person_count):
                out.at[i, 'person_count'] = item.person_count
                out.at[i, 'presence'] = int(item.person_count > 0)
                out.at[i, 'count_class'] = min(int(item.person_count), 3)
                out.at[i, 'label_status'] = 'stable'
        elif ((intervals.start_s < row.window_end_s) & (intervals.end_s > row.feature_start_s)).any():
            out.at[i, 'label_status'] = 'transition_or_partial'
    return out


def load_dataset(manifest_path, labels_path=None, fast_params=None, slow_params=None,
                 use_slow_features=False):
    manifest_path = Path(manifest_path).resolve()
    manifest = pd.read_csv(manifest_path, keep_default_na=False)
    required = {'session_id', 'capture_file', 'split', 'reference', 'room_id', 'placement_id', 'day', 'link_id'}
    if not required.issubset(manifest.columns):
        raise ValueError(f'Manifest missing {sorted(required-set(manifest.columns))}')
    if manifest.session_id.eq('').any() or manifest.duplicated(['session_id', 'link_id']).any():
        raise ValueError('Require session_id and one capture per (session_id, link_id)')
    valid_splits = {'unassigned', 'train', 'validation', 'test'}
    if not set(manifest.split).issubset(valid_splits):
        raise ValueError(f'split must be one of {valid_splits}')
    if (manifest.groupby('session_id')['split'].nunique() > 1).any():
        raise ValueError('All links of a session must have the same split')
    all_rows = []
    fast_config = {**FAST_DEFAULTS, **(fast_params or {})}
    slow_config = {**SLOW_DEFAULTS, **(slow_params or {})}
    paths = set()
    for _, entry in manifest.iterrows():
        capture = (manifest_path.parent / entry.capture_file).resolve()
        if capture in paths:
            raise ValueError('The same capture cannot appear in multiple sessions')
        paths.add(capture)
        time, channel, meta = read_capture(capture)
        meta.pop('sample_timestamps_us')
        fast = extract_features(time, channel, **fast_config)
        slow = extract_features(time, channel, **slow_config)
        for row in fast:
            row.update(entry.to_dict())
            row['reference'] = _bool(entry.reference)
            row.update(meta)
            row['source_capture'] = capture.name
            row['feature_start_s'] = row['window_start_s']
            row['slow_quality_ok'] = False
            row['slow_periodicity_ok'] = False
            row['slow_available_at_s'] = np.nan
            for name in SLOW_FEATURES:
                row[name] = np.nan
            # Backward-only join: a long window is unavailable until it ends.
            eligible = [s for s in slow if s['window_end_s'] <= row['window_end_s']]
            if eligible:
                latest = eligible[-1]
                row['slow_available_at_s'] = latest['window_end_s']
                row['slow_quality_ok'] = latest['quality_ok']
                row['slow_periodicity_ok'] = latest['periodicity_ok']
                if use_slow_features:
                    row['feature_start_s'] = min(row['feature_start_s'], latest['window_start_s'])
                if latest['periodicity_ok']:
                    row['slow_periodic_peak_hz'] = latest['periodic_peak_hz']
                    row['slow_periodic_explained_fraction'] = latest['periodic_explained_fraction']
            all_rows.append(row)
    if not all_rows:
        raise ValueError('No complete fast windows. Adjust extraction or collect a longer capture.')
    frame = pd.DataFrame(all_rows).reset_index(drop=True)
    return attach_labels(frame, load_annotations(labels_path))


def select_features(frame, columns):
    if not columns or len(columns) != len(set(columns)):
        raise ValueError('Select at least one unique feature')
    bad = set(columns) - set(ALLOWED_FEATURES)
    if bad:
        raise ValueError(f'Not predictive features (metadata/labels are prohibited): {sorted(bad)}')
    return frame.loc[:, columns].replace([np.inf, -np.inf], np.nan).astype(float)


def quality_mask(frame, columns):
    mask = frame.quality_ok.astype(bool).copy()
    if any(name in SLOW_FEATURES for name in columns):
        mask &= frame.slow_quality_ok.astype(bool) & frame.slow_periodicity_ok.astype(bool)
    return mask


def assert_disjoint(train, other, group_column=None):
    if train.empty or other.empty:
        return
    if group_column and set(train[group_column]) & set(other[group_column]):
        raise ValueError(f'{group_column} overlaps partitions')
    for session in set(train.session_id) & set(other.session_id):
        a, b = train[train.session_id == session], other[other.session_id == session]
        for _, row in a.iterrows():
            if ((b.feature_start_s < row.window_end_s) & (b.window_end_s > row.feature_start_s)).any():
                raise ValueError('Overlapping raw dependency intervals cross partitions')


def partition_dataset(frame, group_column='session_id', allow_chronological=False, purge_seconds=30):
    """Respect explicit split assignments; optional single-session fallback is marked exploratory."""
    parts = {name: frame[frame.split == name].copy() for name in ['train', 'validation', 'test']}
    mode = 'explicit held-out sessions'
    if not any(len(p) for p in parts.values()):
        if not allow_chronological or frame.session_id.nunique() != 1:
            return parts, 'no split assigned: edit dataset_manifest.csv'
        unique = frame.window_end_s.sort_values().unique()
        t1, t2 = np.quantile(unique, [0.5, 0.75])
        parts['train'] = frame[frame.window_end_s <= t1].copy()
        parts['validation'] = frame[(frame.window_end_s >= t1 + purge_seconds) &
                                     (frame.feature_start_s >= t1) & (frame.window_end_s <= t2)].copy()
        parts['test'] = frame[(frame.window_end_s >= t2 + purge_seconds) &
                               (frame.feature_start_s >= t2)].copy()
        mode = 'exploratory chronological split of ONE session; not independent-session performance'
        group_column = None
    elif (frame.split == 'unassigned').any():
        mode += '; unassigned sessions excluded'
    if group_column:
        if frame[group_column].astype(str).eq('').any():
            raise ValueError(f'Fill {group_column} before using it for grouped splits')
    for a, b in [('train', 'validation'), ('train', 'test'), ('validation', 'test')]:
        assert_disjoint(parts[a], parts[b], group_column)
    return parts, mode


def exposure_seconds(frame):
    """Union of observed feature intervals per session; overlapping windows count once."""
    total = 0.0
    for _, group in frame.groupby('session_id'):
        intervals = sorted(zip(group.feature_start_s, group.window_end_s))
        end = -np.inf
        for start, stop in intervals:
            total += max(0.0, stop-max(start, end))
            end = max(end, stop)
    return total
