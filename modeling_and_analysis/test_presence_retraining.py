"""Guard against temporal leakage and label-dependent preprocessing."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import collect_com4_10min
from csi_dataset import MOTION_FEATURES
from retrain_presence_gmm import fit_candidate, mapped_presence, state_mapping, temporal_splits


class PresenceRetrainingTests(unittest.TestCase):
    def test_temporal_partitions_purge_shared_packet_dependencies(self):
        frame = pd.DataFrame(dict(window_start_s=np.arange(598), window_end_s=np.arange(598)+3))
        result = temporal_splits(frame, 600)
        train = result[result.split.eq('train')]
        validation = result[result.split.eq('validation')]
        test = result[result.split.eq('test')]
        self.assertGreaterEqual(validation.window_start_s.min()-train.window_end_s.max(), 10)
        self.assertGreaterEqual(test.window_start_s.min()-validation.window_end_s.max(), 10)
        self.assertEqual(result.loc[360, 'split'], 'purged')
        self.assertEqual(result.loc[480, 'split'], 'purged')

    def test_component_mapping_uses_arbitrary_component_ids(self):
        states = np.asarray([1, 1, 0, 0])
        presence = np.asarray([0, 0, 1, 1])
        mapping = state_mapping(states, presence)
        self.assertEqual(mapping, {'0': 'occupied', '1': 'empty'})
        np.testing.assert_array_equal(mapped_presence(states, mapping), presence)

    def test_validation_changes_do_not_refit_preprocessing_or_mapping(self):
        rng = np.random.default_rng(42)
        values = rng.normal(size=(100, len(MOTION_FEATURES)))
        values[50:] += 4
        train = pd.DataFrame(values, columns=MOTION_FEATURES)
        train['presence'] = [0]*50+[1]*50
        validation = train.copy()
        shifted = validation.copy()
        shifted[MOTION_FEATURES] += 1000
        shifted.presence = 1-shifted.presence
        a, mapping_a, _ = fit_candidate(train, validation, 'tied')
        b, mapping_b, _ = fit_candidate(train, shifted, 'tied')
        np.testing.assert_allclose(a['scaler'].mean_, train[MOTION_FEATURES].mean())
        np.testing.assert_allclose(a['scaler'].mean_, b['scaler'].mean_)
        np.testing.assert_allclose(a['model'].means_, b['model'].means_)
        self.assertEqual(mapping_a, mapping_b)

    def test_delayed_capture_waits_before_opening_port_and_records_context(self):
        clock = [0.]
        def advance(seconds): clock[0] += seconds
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'empty.csv'
            def capture(argv):
                self.assertGreaterEqual(clock[0], 300)
                output.write_text('local_timestamp,len\n0,128\n1000000,128\n')
                return 0
            with patch.object(collect_com4_10min.time, 'monotonic', side_effect=lambda: clock[0]), \
                 patch.object(collect_com4_10min.time, 'sleep', side_effect=advance), \
                 patch.object(collect_com4_10min.capture_csi, 'main', side_effect=capture):
                self.assertEqual(collect_com4_10min.main([
                    '--delay', '300', '--presence', 'empty', '--output', str(output)]), 0)
            summary = json.loads(output.with_suffix('.summary.json').read_text())
            self.assertEqual(summary['recording_context'], 'empty')
            self.assertEqual(summary['delay_seconds'], 300)
            self.assertEqual(summary['context_source'], 'user')


if __name__ == '__main__':
    unittest.main()
