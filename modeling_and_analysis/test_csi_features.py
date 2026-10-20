"""Run with: python -m unittest test_csi_features.py"""
import unittest
import numpy as np

from csi_features import extract_features


class FeatureTests(unittest.TestCase):
    def test_common_amplitude_scaling_is_removed_by_normalization(self):
        t = np.arange(0, 61, 0.1)
        amplitude = (2 + 0.5*np.sin(2*np.pi*0.25*t))[:, None] * np.array([2, 3, 4])
        row = extract_features(t, amplitude.astype(complex))[0]
        self.assertGreater(row['amplitude_std_median'], 0.5)
        self.assertLess(row['normalized_std_median'], 1e-12)
        self.assertAlmostEqual(row['periodic_explained_fraction'], 0)

    def test_irregular_periodic_signal(self):
        rng = np.random.default_rng(7)
        t = np.cumsum(rng.uniform(0.07, 0.12, 700))
        amplitude = 10 + np.sin(2*np.pi*0.25*t[:, None]) * np.array([1, -1, 0.7, -0.7])
        row = extract_features(t, amplitude.astype(complex))[0]
        self.assertTrue(row['periodicity_ok'])
        self.assertAlmostEqual(row['periodic_peak_hz'], 0.25, delta=0.006)
        self.assertGreater(row['periodic_explained_fraction'], 0.95)

    def test_common_phase_rotation_cancels_without_wrap_artifacts(self):
        t = np.arange(0, 31, 0.1)
        h = np.array([4, 5, 6])[None, :] * np.exp(1j*(2*t[:, None] + np.array([0, 0.2, -0.4])))
        row = extract_features(t, h)[0]
        self.assertAlmostEqual(row['phase_step_abs_median_rad'], 0.2, places=8)
        self.assertLess(row['relative_phase_step_abs_median_rad'], 1e-12)

    def test_gap_blocks_periodicity(self):
        t = np.r_[np.arange(0, 10, 0.1), np.arange(20, 61, 0.1)]
        h = np.ones((len(t), 3), complex)
        row = extract_features(t, h)[0]
        self.assertFalse(row['quality_ok'])
        self.assertFalse(row['periodicity_ok'])
        self.assertTrue(np.isnan(row['periodic_peak_hz']))

    def test_invalid_and_zero_bins_and_sparse_windows(self):
        t = np.arange(0, 31, 0.1)
        h = np.ones((len(t), 4), complex)
        h[:, 0] = np.nan
        h[:, 1] = 0
        h[5, 2] = np.nan
        row = extract_features(t, h)[0]
        self.assertEqual(row['bin_count'], 2)
        self.assertGreater(row['imputed_fraction'], 0)
        sparse = extract_features(np.array([0, 10, 31]), np.ones((3, 2)))[0]
        self.assertFalse(sparse['quality_ok'])
        self.assertTrue(np.isnan(sparse['amplitude_std_median']))

    def test_bad_timestamps_and_short_capture(self):
        with self.assertRaises(ValueError):
            extract_features([0, 3, 1], np.ones((3, 2)))
        self.assertEqual(extract_features([0, 1], np.ones((2, 2))), [])


if __name__ == '__main__':
    unittest.main()
