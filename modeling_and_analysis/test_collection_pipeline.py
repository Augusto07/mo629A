"""Transport boundaries must not change CSI feature windows or predictions."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from collection_pipeline import CaptureWindowBuffer, load_collection_export, predict_collection_batches
from csi_features import extract_features
import standalone_gmm as model


def batches(seconds=8, size=20, origin=2**53 + 3, rate=50):
    samples = [dict(seq=i, timestamp_us=origin + i * (1_000_000 // rate),
                    csi_raw=[(i * 3 + k * 7) % 41 - 20 for k in range(128)],
                    first_word_invalid=i % 7 == 0, ap_mac='ap-a', channel=4, bandwidth_mhz=20)
               for i in range(seconds * rate + 1)]
    return [dict(schema_version=1, device_id='device-a', session_id='session-a',
                 batch_id=i//size, samples=samples[i:i+size]) for i in range(0, len(samples), size)]


class CollectionTests(unittest.TestCase):
    def setUp(self):
        # Test the transport/window contract at a fixed reference configuration,
        # independently of whichever fitted model is currently active.
        context = patch.dict(model.PROVENANCE['metadata'], {
            'fast_parameters': dict(window_seconds=5., hop_seconds=1., min_packets=12, max_gap_seconds=2.),
            'input_filter': None,
        })
        context.start()
        self.addCleanup(context.stop)

    def test_fractional_hop_overrides_are_independent_of_upload_boundaries(self):
        inputs = batches()
        settings = dict(window_seconds=1, hop_seconds=0.2, min_packets=10, max_gap_seconds=0.1)
        actual = predict_collection_batches(inputs, model, parameters=settings)
        combined = [dict(inputs[0], samples=[s for b in inputs for s in b['samples']])]
        expected = predict_collection_batches(combined, model, parameters=settings)
        self.assert_equivalent(actual['windows'], expected['windows'])
        self.assertEqual(len(actual['windows']), 36)
        self.assertFalse(actual['settings_match_training'])
        self.assertEqual(actual['window_parameters'], settings)
        for index, row in enumerate(actual['windows']):
            self.assertEqual(row['packet_count'], 50)
            self.assertEqual(row['window_start_timestamp_us'], inputs[0]['samples'][0]['timestamp_us'] + index*200_000)
            self.assertEqual(row['window_end_timestamp_us']-row['window_start_timestamp_us'], 1_000_000)
            self.assertEqual(row['inference_mode'], 'exploratory_window_override')
        self.assertEqual(model.PROVENANCE['metadata']['fast_parameters']['window_seconds'], 5)

    def test_packet_and_gap_overrides_change_quality_without_changing_the_model(self):
        inputs = batches(seconds=2, rate=10)
        common = dict(window_seconds=1, hop_seconds=0.5, min_packets=8, max_gap_seconds=0.2)
        passing = predict_collection_batches(inputs, model, common)
        sparse = predict_collection_batches(inputs, model, dict(common, min_packets=12))
        gaps = predict_collection_batches(inputs, model, dict(common, max_gap_seconds=0.05))
        self.assertEqual(passing['captures'][0]['accepted_windows'], 3)
        self.assertEqual(sparse['captures'][0]['accepted_windows'], 0)
        self.assertEqual(gaps['captures'][0]['accepted_windows'], 0)
        self.assertEqual(gaps['captures'][0]['gaps_over_limit'], 20)
        self.assertTrue(all(row['observed_max_gap_s'] > 0.05 for row in gaps['windows']))

    def test_invalid_window_overrides_fail_even_without_packets(self):
        for settings in ({'window_seconds': 0}, {'window_seconds': 1e300}, {'hop_seconds': float('nan')},
                         {'hop_seconds': 0.0000001}, {'min_packets': 2},
                         {'min_packets': 3.5}, {'max_gap_seconds': -1}, {'unknown': 1}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                predict_collection_batches([], model, settings)

    def assert_equivalent(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        self.assertEqual([r['state'] for r in actual], [r['state'] for r in expected])
        self.assertEqual([r['quality_ok'] for r in actual], [r['quality_ok'] for r in expected])
        np.testing.assert_allclose([[r[name] for name in model.FEATURES] for r in actual],
                                   [[r[name] for name in model.FEATURES] for r in expected], equal_nan=True)

    def test_upload_boundaries_and_receipt_times_do_not_change_predictions(self):
        inputs = batches()
        samples = [s for batch in inputs for s in batch['samples']]
        raw = [dict(data=s['csi_raw'], local_timestamp=s['timestamp_us']-samples[0]['timestamp_us'],
                    len=128, first_word=int(s['first_word_invalid'])) for s in samples]
        expected = model.predict_input(raw, kind='raw')
        actual = predict_collection_batches(inputs, model)
        self.assert_equivalent(actual['windows'], expected)
        self.assertEqual(len(actual['windows']), 4)
        for row in actual['windows']:
            self.assertEqual(row['packet_count'], 250)
            self.assertGreater(len(row['source_batch_ids']), 1)
            self.assertEqual(len(row['sample_timestamps_us']), 250)
            self.assertEqual(row['window_start_timestamp_us'] % 1_000_000,
                             samples[0]['timestamp_us'] % 1_000_000)
        for item in inputs:
            item['timestamp_received'] = '2099-12-31T23:59:59+00:00'
        self.assert_equivalent(predict_collection_batches(list(reversed(inputs)), model)['windows'], expected)
        combined = [dict(inputs[0], samples=samples)]
        self.assert_equivalent(predict_collection_batches(combined, model)['windows'], expected)

    def test_partial_windows_survive_push_and_packet_storage_is_pruned(self):
        buffer = CaptureWindowBuffer(model)
        windows = []
        for item in batches(seconds=12):
            packets = [dict(s, batch_id=item['batch_id']) for s in item['samples']]
            new = buffer.push(packets)
            if item['batch_id'] < 12:
                self.assertFalse(new)
            windows.extend(new)
            self.assertLessEqual(len(buffer.pending), 270)
        self.assertEqual(len(windows), 8)
        self.assertEqual(len({row['window_start_timestamp_us'] for row in windows}), 8)
        self.assertEqual(len(buffer.pending), 201)
        self.assertEqual(buffer.push([]), [])

    def test_pause_and_missing_uploads_remain_unknown(self):
        inputs = batches(seconds=12)
        inputs = [b for b in inputs if b['batch_id'] < 3 or b['batch_id'] >= 25]
        result = predict_collection_batches(inputs, model)
        self.assertEqual(result['captures'][0]['accepted_windows'], 0)
        self.assertGreater(result['captures'][0]['longest_gap_s'], 2)
        self.assertGreater(result['captures'][0]['sequence_gaps'], 0)
        self.assertTrue(all(r['status'] == 'insufficient_data' and r['state'] is None for r in result['windows']))
        self.assertTrue(any(r['packet_count'] == 0 for r in result['windows']))

    def test_duplicates_conflicts_and_clock_reset(self):
        inputs = batches()
        expected = predict_collection_batches(inputs, model)
        duplicate = predict_collection_batches(inputs + [copy.deepcopy(inputs[0])], model)
        self.assert_equivalent(duplicate['windows'], expected['windows'])
        self.assertEqual(duplicate['captures'][0]['duplicates_removed'], 20)
        changed = copy.deepcopy(inputs[0])
        changed['samples'][0]['csi_raw'][0] += 1
        conflicting = predict_collection_batches(inputs + [changed], model)
        self.assertEqual(conflicting['captures'][0]['status'], 'conflicting_duplicates')
        self.assertFalse(conflicting['windows'])
        broken = copy.deepcopy(inputs)
        broken[-1]['samples'][-1]['timestamp_us'] = 0
        self.assertEqual(predict_collection_batches(broken, model)['captures'][0]['status'], 'invalid_clock_or_sequence')

    def test_session_channel_length_and_malformed_packet_isolation(self):
        first = batches(seconds=6)
        second = copy.deepcopy(first)
        for item in second:
            item['session_id'] = 'session-b'
            for sample in item['samples']:
                sample['channel'] = 6
        short = copy.deepcopy(first[0])
        short['device_id'] = 'unsupported'
        for sample in short['samples']:
            sample['csi_raw'] = [1, 2]
        invalid = copy.deepcopy(first[0])
        invalid['samples'] = [dict(invalid['samples'][0], timestamp_us=1.5)]
        result = predict_collection_batches(first + second + [short, invalid], model)
        self.assertEqual(len(result['issues']), 1)
        self.assertEqual(len(result['windows']), 4)
        self.assertEqual({r['session_id'] for r in result['windows']}, {'session-a', 'session-b'})
        self.assertEqual(result['captures'][-1]['status'], 'unsupported_csi_length')

    def test_csv_dynamodb_numbers_keep_integer_precision(self):
        def wrap(value):
            if isinstance(value, bool): return {'BOOL': value}
            if isinstance(value, int): return {'N': str(value)}
            if isinstance(value, str): return {'S': value}
            if isinstance(value, list): return {'L': [wrap(v) for v in value]}
            return {'M': {k: wrap(v) for k, v in value.items()}}
        item = batches(seconds=1)[0]
        original = item['samples'][0]['timestamp_us']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'export.csv'
            with path.open('w', newline='') as output:
                writer = csv.DictWriter(output, fieldnames=list(item))
                writer.writeheader()
                writer.writerow(dict(item, samples=json.dumps([wrap(s) for s in item['samples']])))
                writer.writerow(dict(item, samples='invalid JSON'))
            loaded, issues = load_collection_export(path)
        self.assertEqual(loaded[0]['samples'][0]['timestamp_us'], original)
        self.assertEqual(len(issues), 1)
        self.assertFalse(predict_collection_batches(loaded, model)['windows'])

    def test_explicit_window_bounds_keep_unobserved_edges_and_empty_windows(self):
        h = np.ones((20, 64), complex)
        rows = extract_features(np.linspace(3, 4, 20), h, window_seconds=5, hop_seconds=1,
                                start_s=0, end_s=5)
        self.assertFalse(rows[0]['quality_ok'])
        self.assertEqual(rows[0]['max_gap_s'], 3)
        empty = extract_features([], np.empty((0, 64), complex), window_seconds=5,
                                 start_s=0, end_s=5)
        self.assertEqual(empty[0]['packet_count'], 0)
        self.assertFalse(empty[0]['quality_ok'])


if __name__ == '__main__':
    unittest.main()
