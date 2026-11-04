"""Local CSI inference across small uploads; no AWS or Lambda dependencies.

Collection clocks are 64-bit microsecond counters. Receipt time is diagnostic
only: buffering, upload jitter and pauses must not alter feature timing.
"""
from collections import defaultdict
import csv
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

import numpy as np

from csi_features import extract_features


IDENTITY_FIELDS = ('device_id', 'session_id', 'ap_mac', 'channel', 'bandwidth_mhz', 'csi_length', 'sig_mode')
WINDOW_FIELDS = ('window_seconds', 'hop_seconds', 'min_packets', 'max_gap_seconds')


def exact_int(value, name):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be an integer, not a boolean')
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f'{name} must be an integer') from error
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f'{name} must be a finite integer')
    return int(number)


def decode_dynamodb(value):
    if isinstance(value, list):
        return [decode_dynamodb(item) for item in value]
    if not isinstance(value, dict):
        return value
    if len(value) == 1:
        kind, item = next(iter(value.items()))
        if kind == 'M':
            return {key: decode_dynamodb(val) for key, val in item.items()}
        if kind == 'L':
            return [decode_dynamodb(val) for val in item]
        if kind == 'N':
            number = Decimal(item)
            if not number.is_finite():
                raise ValueError('Nonfinite DynamoDB number')
            return int(number) if number == number.to_integral_value() else float(number)
        if kind == 'S':
            return str(item)
        if kind == 'BOOL' and isinstance(item, bool):
            return item
        if kind == 'NULL':
            return None
        raise ValueError(f'Unsupported or malformed DynamoDB attribute: {kind}')
    return {key: decode_dynamodb(item) for key, item in value.items()}


def load_collection_export(path):
    """Return normalized batches and row issues from a DynamoDB CSV export."""
    batches, issues = [], []
    csv.field_size_limit(100_000_000)
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        required = {'device_id', 'session_id', 'samples', 'schema_version', 'batch_id'}
        if missing := required - set(reader.fieldnames or []):
            raise ValueError(f'Collection export is missing columns: {sorted(missing)}')
        for csv_row, row in enumerate(reader, start=2):
            try:
                row['samples'] = decode_dynamodb(json.loads(row['samples']))
                row['csv_row'] = csv_row
                batches.append(row)
            except (ValueError, TypeError) as error:
                issues.append(dict(csv_row=csv_row, sample_index=None, reason=str(error)))
    return batches, issues


def _packets(batches):
    packets, issues, batch_summary = [], [], []
    for source_index, item in enumerate(batches):
        csv_row = item.get('csv_row', source_index + 2)
        try:
            if exact_int(item.get('schema_version', 1), 'schema_version') != 1:
                raise ValueError('Only collection schema_version 1 is supported')
            device, session = item['device_id'], item['session_id']
            if not isinstance(device, str) or not device.strip() or not isinstance(session, str) or not session.strip():
                raise ValueError('Missing device_id or session_id')
            batch_id = exact_int(item['batch_id'], 'batch_id')
            if batch_id < 0:
                raise ValueError('Negative batch_id')
            samples = decode_dynamodb(item['samples'])
            if not isinstance(samples, list):
                raise ValueError('samples must be an array')
        except (KeyError, ValueError, TypeError) as error:
            issues.append(dict(csv_row=csv_row, sample_index=None, reason=str(error)))
            continue
        stamps = []
        for sample_index, sample in enumerate(samples):
            try:
                if not isinstance(sample['csi_raw'], list):
                    raise ValueError('csi_raw must be an array')
                values = [exact_int(value, 'csi_raw') for value in sample['csi_raw']]
                if not values or len(values) % 2 or any(v < -128 or v > 127 for v in values):
                    raise ValueError('CSI must contain signed int8 I/Q pairs')
                stamp = exact_int(sample['timestamp_us'], 'timestamp_us')
                seq = exact_int(sample['seq'], 'seq')
                if not 0 <= stamp < 2**63 or not 0 <= seq < 2**32:
                    raise ValueError('Timestamp or sequence outside collector range')
                invalid = sample.get('first_word_invalid', False)
                if not isinstance(invalid, bool):
                    invalid = exact_int(invalid, 'first_word_invalid')
                if invalid not in (0, 1):
                    raise ValueError('first_word_invalid must be boolean or 0/1')
                ap = sample['ap_mac']
                if not isinstance(ap, str) or not ap.strip():
                    raise ValueError('Missing ap_mac')
                packet = dict(device_id=device, session_id=session, ap_mac=ap,
                              channel=exact_int(sample['channel'], 'channel'),
                              bandwidth_mhz=exact_int(sample['bandwidth_mhz'], 'bandwidth_mhz'),
                              csi_length=len(values), csi_raw=values, timestamp_us=stamp, seq=seq,
                              sig_mode=exact_int(sample.get('sig_mode', -1), 'sig_mode'),
                              first_word_invalid=bool(invalid), batch_id=batch_id,
                              timestamp_received=item.get('timestamp_received') or None,
                              csv_row=csv_row, sample_index=sample_index)
                packets.append(packet)
                stamps.append(stamp)
            except (KeyError, ValueError, TypeError) as error:
                issues.append(dict(csv_row=csv_row, sample_index=sample_index, reason=str(error)))
        batch_summary.append(dict(device_id=device, session_id=session, batch_id=batch_id,
                                  csv_row=csv_row, packet_count=len(stamps),
                                  first_timestamp_us=min(stamps) if stamps else None,
                                  last_timestamp_us=max(stamps) if stamps else None,
                                  duration_s=(max(stamps)-min(stamps))/1e6 if stamps else 0.0))
    return packets, issues, batch_summary


def resolve_window_parameters(model, parameters=None):
    """Use training settings as defaults; validate explicit local overrides."""
    resolved = {name: model.PROVENANCE['metadata']['fast_parameters'][name] for name in WINDOW_FIELDS}
    overrides = {} if parameters is None else dict(parameters)
    if unknown := set(overrides) - set(WINDOW_FIELDS):
        raise ValueError(f'Unknown window parameters: {sorted(unknown)}')
    resolved.update(overrides)
    for name in ('window_seconds', 'hop_seconds', 'max_gap_seconds'):
        value = resolved[name]
        if isinstance(value, bool):
            raise ValueError(f'{name} must be positive seconds')
        try:
            seconds = Decimal(str(value))
            micros = seconds * 1_000_000
            if (not seconds.is_finite() or seconds <= 0 or micros > 2**63-1 or
                    micros != micros.to_integral_value()):
                raise ValueError(f'{name} must be positive whole microseconds expressed as seconds')
        except InvalidOperation as error:
            raise ValueError(f'{name} must be positive seconds') from error
        resolved[name] = float(seconds)
    resolved['min_packets'] = exact_int(resolved['min_packets'], 'min_packets')
    if resolved['min_packets'] < 3:
        raise ValueError('min_packets must be at least 3 for feature extraction')
    return resolved


class CaptureWindowBuffer:
    """Incremental buffer for one capture, fed ordered, deduplicated packets.

    push() returns only newly complete windows. Packet storage is pruned after
    each push; incomplete windows remain available to the next upload. All
    window arithmetic uses integer acquisition microseconds before converting
    offsets to seconds for the original feature extractor.
    """
    def __init__(self, model, parameters=None):
        self.model = model
        self.parameters = resolve_window_parameters(model, parameters)
        self.settings_match_training = self.parameters == resolve_window_parameters(model)
        self.window_us = round(self.parameters['window_seconds'] * 1e6)
        self.hop_us = round(self.parameters['hop_seconds'] * 1e6)
        self.origin_us = self.next_start_us = self.last_stamp = self.last_seq = None
        self.pending = []

    def push(self, packets):
        if not packets:
            return []
        for packet in packets:
            stamp, seq = packet['timestamp_us'], packet['seq']
            if self.last_stamp is not None and (stamp < self.last_stamp or seq <= self.last_seq):
                raise ValueError('Clock reset/out-of-order packets; split sessions first')
            if self.origin_us is None:
                self.origin_us = self.next_start_us = stamp
            self.pending.append(packet)
            self.last_stamp, self.last_seq = stamp, seq
        if self.next_start_us + self.window_us > self.last_stamp:
            return []
        stamps = np.asarray([p['timestamp_us'] for p in self.pending], dtype=np.int64)
        raw = np.asarray([p['csi_raw'] for p in self.pending], dtype=float)
        channel = raw[:, 1::2] + 1j * raw[:, 0::2]
        channel[np.asarray([p['first_word_invalid'] for p in self.pending], dtype=bool), :2] = complex(np.nan, np.nan)
        rows = []
        count = (self.last_stamp-self.next_start_us-self.window_us)//self.hop_us + 1
        for index in range(count):
            start = self.next_start_us + index * self.hop_us
            stop = start + self.window_us
            # Integer membership avoids floating-hop drift at packet boundaries.
            mask = (stamps >= start) & (stamps < stop)
            row = extract_features((stamps[mask]-start)/1e6, channel[mask], **self.parameters,
                                   start_s=0.0, end_s=self.parameters['window_seconds'])[0]
            row.update(window_start_s=(start-self.origin_us)/1e6,
                       window_end_s=(stop-self.origin_us)/1e6,
                       window_center_s=(start-self.origin_us+self.window_us/2)/1e6)
            members = [p for p in self.pending if start <= p['timestamp_us'] < stop]
            timestamps = [p['timestamp_us'] for p in members]
            gaps = np.diff([start, *timestamps, stop]) / 1e6
            row.update(window_start_timestamp_us=start, window_end_timestamp_us=stop,
                       sample_timestamps_us=timestamps,
                       source_batch_ids=sorted({p['batch_id'] for p in members}),
                       observed_max_gap_s=float(max(gaps)),
                       observed_packet_rate_hz=(len(members)-1)*1e6/(timestamps[-1]-timestamps[0])
                       if len(members) > 1 and timestamps[-1] > timestamps[0] else 0.0)
            row['inference_mode'] = ('training_window_settings' if self.settings_match_training
                                     else 'exploratory_window_override')
            rows.append(row)
        self.next_start_us += len(rows) * self.hop_us
        self.pending = [p for p in self.pending if p['timestamp_us'] >= self.next_start_us]
        rows = self.model.predict_records(rows)
        for row in rows:
            row['rejection_reason'] = (
                'accepted' if row['status'] == 'ok' else
                f"fewer than {self.parameters['min_packets']} packets" if row['packet_count'] < self.parameters['min_packets'] else
                f"gap exceeds {self.parameters['max_gap_seconds']:g} s" if row['observed_max_gap_s'] > self.parameters['max_gap_seconds'] else
                'sampling quality failed')
        return rows


def predict_collection_batches(batches, model, parameters=None):
    """Infer locally across uploads, isolating malformed/unsupported captures.

    Export order is arbitrary. Sequence conflicts and clock regressions reject
    the affected capture rather than silently manufacturing continuity.
    """
    parameters = resolve_window_parameters(model, parameters)
    training_parameters = resolve_window_parameters(model)
    packets, issues, batch_summary = _packets(batches)
    groups = defaultdict(list)
    for packet in packets:
        groups[tuple(packet[name] for name in IDENTITY_FIELDS)].append(packet)
    windows, captures, packet_index = [], [], []
    for capture_number, (key, group) in enumerate(sorted(groups.items()), start=1):
        capture_id = f'capture_{capture_number:03d}'
        identity = dict(zip(IDENTITY_FIELDS, key))
        ordered = sorted(group, key=lambda p: (p['batch_id'], p['seq']))
        seen, unique, conflict = {}, [], False
        for packet in ordered:
            fingerprint = (packet['timestamp_us'], packet['first_word_invalid'], tuple(packet['csi_raw']))
            if packet['seq'] in seen:
                conflict |= seen[packet['seq']] != fingerprint
            else:
                seen[packet['seq']] = fingerprint
                unique.append(packet)
        summary = dict(capture_id=capture_id, **identity, packet_records=len(group),
                       unique_packets=len(unique), duplicates_removed=len(group)-len(unique),
                       batches=len({p['batch_id'] for p in unique}), sequence_gaps=0,
                       duration_s=0.0, gaps_over_2s=0, longest_gap_s=0.0,
                       gap_limit_s=parameters['max_gap_seconds'], gaps_over_limit=0,
                       windows=0, accepted_windows=0, unknown_windows=0,
                       trailing_packet_count=0, trailing_span_s=0.0, detail='')
        for packet in unique:
            packet_index.append(dict(packet, capture_id=capture_id,
                                     time_s=(packet['timestamp_us']-unique[0]['timestamp_us'])/1e6))
        if conflict:
            summary.update(status='conflicting_duplicates', detail='Conflicting copies of one sequence number')
        elif identity['csi_length'] != 128:
            summary.update(status='unsupported_csi_length', detail='Expected 128 I/Q values per packet')
        elif not matches_training_radio(identity, model):
            summary.update(status='unsupported_radio_format',
                           detail='Radio metadata does not match the selected model; missing sig_mode is unverified')
        elif any(b['timestamp_us'] < a['timestamp_us'] or b['seq'] <= a['seq'] for a, b in zip(unique, unique[1:])):
            summary.update(status='invalid_clock_or_sequence', detail='Clock reset/out-of-order packets; split sessions first')
        else:
            gaps = [(b['timestamp_us']-a['timestamp_us'])/1e6 for a, b in zip(unique, unique[1:])]
            summary.update(duration_s=(unique[-1]['timestamp_us']-unique[0]['timestamp_us'])/1e6,
                           sequence_gaps=sum(max(b['seq']-a['seq']-1, 0) for a, b in zip(unique, unique[1:])),
                           gaps_over_2s=sum(g > 2.0 for g in gaps),
                           gaps_over_limit=sum(g > parameters['max_gap_seconds'] for g in gaps),
                           longest_gap_s=max(gaps, default=0.0))
            buffer = CaptureWindowBuffer(model, parameters)
            rows = []
            # Preserve upload boundaries to exercise exactly the incremental path.
            by_batch = defaultdict(list)
            for packet in unique:
                by_batch[packet['batch_id']].append(packet)
            for members in by_batch.values():
                rows.extend(buffer.push(members))
            for row in rows:
                row.update(capture_id=capture_id, **identity)
            windows.extend(rows)
            accepted = sum(row['status'] == 'ok' for row in rows)
            summary.update(windows=len(rows), accepted_windows=accepted, unknown_windows=len(rows)-accepted,
                           status=('evaluated' if accepted else 'no_accepted_windows') if rows else 'too_short',
                           trailing_packet_count=len(buffer.pending),
                           trailing_span_s=max(0, buffer.last_stamp-buffer.next_start_us)/1e6)
        captures.append(summary)
    return dict(windows=windows, captures=captures, packets=packet_index,
                batches=batch_summary, issues=issues, window_parameters=parameters,
                training_window_parameters=training_parameters,
                settings_match_training=parameters == training_parameters)


def matches_training_radio(identity, model):
    """A format-specific model cannot validate an absent PHY-mode field."""
    expected = model.PROVENANCE['metadata'].get('input_filter') or {}
    available = dict(mac=identity['ap_mac'], channel=identity['channel'],
                     sig_mode=identity['sig_mode'], len=identity['csi_length'],
                     bandwidth=1 if identity['bandwidth_mhz'] == 40 else 0)
    return all(str(available.get(name, '')) == str(value) for name, value in expected.items())
