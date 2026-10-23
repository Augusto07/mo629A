"""Synthetic implementation checks; these are not occupancy accuracy claims."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

import joblib
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
from sklearn.dummy import DummyClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from csi_dataset import (assert_disjoint, attach_labels, exposure_seconds, load_annotations,
                         load_dataset, partition_dataset, quality_mask, select_features)
from csi_models import (compare_classifiers, compare_unsupervised, cusum_trace,
                        run_change_models, save_bundle, predict_bundle, session_mean_interval)


FEATURES = ['amplitude_mean', 'normalized_std_median']


def synthetic_frame(sessions=6, rows=40, seed=2):
    rng = np.random.default_rng(seed)
    data = []
    for session in range(sessions):
        for i in range(rows):
            label = int(i >= rows//2)
            data.append(dict(session_id=f's{session}', link_id='a', day=f'd{session}',
                split='train' if session < sessions-2 else ('validation' if session == sessions-2 else 'test'),
                reference=False, feature_start_s=float(i*6), window_start_s=float(i*6),
                window_end_s=float(i*6+5), quality_ok=True, slow_quality_ok=False,
                slow_periodicity_ok=False, presence=label, person_count=label,
                count_class=label, activity='synthetic', label_status='stable',
                amplitude_mean=float(1+4*label+rng.normal(0, 0.15)),
                normalized_std_median=float(label+rng.normal(0, 0.05))))
    return pd.DataFrame(data)


class DatasetTests(unittest.TestCase):
    def test_split_rejects_raw_overlap_and_groups(self):
        f = synthetic_frame(3)
        train = f.iloc[:10]
        with self.assertRaises(ValueError):
            assert_disjoint(train, f.iloc[5:15])
        with self.assertRaises(ValueError):
            assert_disjoint(train, f.iloc[15:20], 'session_id')
        assert_disjoint(train, f[f.session_id == 's1'], 'session_id')

    def test_chronological_purge_and_exposure_union(self):
        f = synthetic_frame(1, 100)
        f['split'] = 'unassigned'
        f['feature_start_s'] = f.window_end_s-30
        parts, mode = partition_dataset(f, allow_chronological=True, purge_seconds=30)
        self.assertIn('ONE session', mode)
        self.assertGreater(len(parts['validation']), 0)
        assert_disjoint(parts['train'], parts['validation'])
        a = pd.DataFrame(dict(session_id=['a', 'a'], feature_start_s=[0, 5], window_end_s=[10, 15]))
        self.assertEqual(exposure_seconds(a), 15)

    def test_transition_windows_and_metadata_exclusion(self):
        f = synthetic_frame(1, 3)
        f.loc[0, ['feature_start_s', 'window_end_s']] = [0, 5]
        f.loc[1, ['feature_start_s', 'window_end_s']] = [3, 8]
        labels = pd.DataFrame([dict(session_id='s0', start_s=0, end_s=6, person_count=0, activity='empty'),
                               dict(session_id='s0', start_s=6, end_s=20, person_count=2, activity='seated')])
        out = attach_labels(f, labels)
        self.assertEqual(out.iloc[0].presence, 0)
        self.assertTrue(np.isnan(out.iloc[1].presence))
        self.assertEqual(out.iloc[1].label_status, 'transition_or_partial')
        with self.assertRaises(ValueError):
            select_features(f, ['presence'])
        with self.assertRaises(ValueError):
            select_features(f, ['window_end_s'])

    def test_capture_loader_and_causal_long_join(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            capture = folder/'raw.csv'
            with capture.open('w', newline='') as stream:
                fields = ['type', 'len', 'first_word', 'local_timestamp', 'mac', 'channel', 'sig_mode', 'bandwidth', 'data']
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for i in range(401):
                    writer.writerow(dict(type='CSI_DATA', len=8, first_word=0, local_timestamp=i*100000,
                        mac='a', channel=1, sig_mode=0, bandwidth=0,
                        data=json.dumps([1, 10+int(2*np.sin(i/10)), 2, 20, 3, 15, 1, 25])))
            manifest = pd.DataFrame([dict(session_id='a', capture_file='raw.csv', split='unassigned',
                reference=False, room_id='r', placement_id='p', day='d', link_id='l')])
            manifest.to_csv(folder/'manifest.csv', index=False)
            f = load_dataset(folder/'manifest.csv', use_slow_features=True)
            self.assertTrue((f.slow_available_at_s.dropna() <= f.loc[f.slow_available_at_s.notna(), 'window_end_s']).all())
            self.assertTrue(f.loc[f.window_end_s < 30, 'slow_available_at_s'].isna().all())
            self.assertTrue(f.person_count.isna().all())

    def test_annotation_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'labels.csv'
            pd.DataFrame([dict(session_id='a', start_s=0, end_s=10, person_count='two', activity='', notes='')]).to_csv(path, index=False)
            with self.assertRaises(ValueError):
                load_annotations(path)


class ModelTests(unittest.TestCase):
    def test_unsupervised_fit_does_not_learn_validation_scaling(self):
        f = synthetic_frame()
        train, val = f[f.split == 'train'], f[f.split == 'validation']
        pipe = Pipeline([('imputer', SimpleImputer()), ('scaler', StandardScaler()),
                         ('model', GaussianMixture(n_components=2, random_state=1))])
        val = val.copy()
        val['amplitude_mean'] += 100
        metrics, results = compare_unsupervised([dict(name='gmm', pipeline=pipe)], train, val, FEATURES,
                                                stability_seeds=[2])
        self.assertEqual(metrics.iloc[0].status, 'ok')
        fitted = results['gmm']['pipeline']
        np.testing.assert_allclose(fitted['scaler'].mean_, train[FEATURES].mean())
        self.assertFalse(hasattr(pipe['scaler'], 'mean_'))

    def test_grouped_classification_and_save_load(self):
        f = synthetic_frame()
        train, val = f[f.split == 'train'], f[f.split == 'validation']
        pipe = Pipeline([('scaler', StandardScaler()), ('model', LogisticRegression())])
        metrics, results = compare_classifiers([dict(name='lr', pipeline=pipe)], train, val, FEATURES)
        self.assertEqual(metrics.iloc[0].status, 'ok')
        self.assertGreater(metrics.iloc[0].validation_macro_f1, 0.95)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'model.joblib'
            save_bundle(path, results['lr']['pipeline'], FEATURES, {'purpose': 'synthetic'})
            bundle = joblib.load(path)
            np.testing.assert_array_equal(predict_bundle(bundle, val), results['lr']['prediction'])
            bad = val.copy()
            bad.loc[bad.index[0], 'quality_ok'] = False
            self.assertTrue(np.isnan(predict_bundle(bundle, bad)[0]))
            # Input dataframe order cannot silently change the learned feature order.
            np.testing.assert_array_equal(predict_bundle(bundle, val[val.columns[::-1]]), results['lr']['prediction'])

    def test_unlabeled_data_is_skipped(self):
        f = synthetic_frame()
        f['presence'] = np.nan
        pipe = Pipeline([('model', DummyClassifier())])
        metrics, fitted = compare_classifiers([dict(name='dummy', pipeline=pipe)], f, f.iloc[:0], FEATURES)
        self.assertEqual(metrics.iloc[0].status, 'skipped')
        self.assertFalse(fitted)
        cov = Pipeline([('scaler', StandardScaler()), ('model', LedoitWolf())])
        events = pd.DataFrame(columns=['session_id', 'time_s'])
        metrics, fitted = run_change_models([dict(name='cov', pipeline=cov)], f, f.iloc[:0], FEATURES, events)
        self.assertEqual(metrics.iloc[0].status, 'skipped')
        self.assertFalse(fitted)

    def test_cusum_shift_outage_and_session_reset(self):
        f = synthetic_frame(1, 20)
        f['session_id'] = ['a']*15+['b']*5
        score = np.r_[np.ones(5), np.ones(10)*10, np.ones(5)]
        trace = cusum_trace(f, score, center=1, scale=1, threshold=8, reset_gap_s=7)
        self.assertFalse(trace.event.iloc[:5].any())
        self.assertTrue(trace.event.iloc[5:15].any())
        self.assertFalse(trace.alarm.iloc[15:].any())
        score[8] = np.nan
        trace = cusum_trace(f, score, center=1, scale=1, threshold=8, reset_gap_s=7)
        self.assertEqual(trace.status.iloc[8], 'insufficient_data')

    def test_reference_model_shift_and_frozen_reference(self):
        rng = np.random.default_rng(4)
        f = synthetic_frame(4, 60)
        for name in FEATURES:
            f[name] = rng.normal(0, 0.1, len(f))
        train = f[f.session_id == 's0'].copy()
        val = f[f.session_id == 's1'].copy()
        test = f[f.session_id == 's2'].copy()
        train['reference'] = val['reference'] = True
        test.loc[test.index[30:], FEATURES] += 5
        pipe = Pipeline([('scaler', StandardScaler()), ('model', LedoitWolf())])
        events = pd.DataFrame([dict(session_id='s2', time_s=float(test.iloc[30].window_start_s))])
        metrics, fitted = run_change_models([dict(name='cov', pipeline=pipe)], train, val, FEATURES, events,
            evaluation=test, false_alarm_target_per_hour=0,
            cusum_parameters={'reset_gap_s': 7, 'allowance': 2},
            threshold_grid=[32], event_tolerance_s=20)
        self.assertEqual(metrics.iloc[0].status, 'ok')
        self.assertEqual(metrics.iloc[0].event_recall, 1)
        self.assertGreater(fitted['cov']['trace'].score.iloc[35], fitted['cov']['trace'].score.iloc[5]*10)
        np.testing.assert_allclose(fitted['cov']['pipeline']['scaler'].mean_, train[FEATURES].mean())

    def test_extra_scoring_and_session_interval(self):
        f = synthetic_frame()
        pipe = Pipeline([('scaler', StandardScaler()), ('model', GaussianMixture(n_components=1))])
        metrics, _ = compare_unsupervised([dict(name='gmm', pipeline=pipe)], f[f.split=='train'],
            f[f.split=='validation'], FEATURES, stability_seeds=[],
            extra_metrics={'custom': lambda context: len(context['train_labels'])})
        self.assertEqual(metrics.iloc[0]['custom'], len(f[f.split=='train']))
        mean, lower, upper = session_mean_interval([0.7, 0.8, 0.9])
        self.assertLessEqual(lower, mean)
        self.assertGreaterEqual(upper, mean)
        self.assertTrue(np.isnan(session_mean_interval([1, 1])[0]))


if __name__ == '__main__':
    unittest.main()
