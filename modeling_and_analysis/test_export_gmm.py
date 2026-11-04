"""Selected analysis bundles must reproduce sklearn in exported inference."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_selection import VarianceThreshold
from sklearn.impute import SimpleImputer
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from collection_pipeline import predict_collection_batches
from csi_dataset import MOTION_FEATURES
from export_gmm import export_gmm
from test_collection_pipeline import batches


class ExportTests(unittest.TestCase):
    def fitted_bundle(self, directory, covariance='tied'):
        rng = np.random.default_rng(42)
        x = rng.normal(size=(80, len(MOTION_FEATURES)))
        x[40:] += 2
        x[:, -1] = 1  # Exercise the fitted variance filter, not just identity.
        x[::7, 0] = np.nan
        frame = pd.DataFrame(x, columns=MOTION_FEATURES)
        pipeline = Pipeline([
            ('imputer', SimpleImputer(strategy='median')),
            ('variance', VarianceThreshold()), ('scaler', StandardScaler()),
            ('model', GaussianMixture(n_components=2, covariance_type=covariance,
                                      random_state=42, n_init=2, reg_covar=1e-4)),
        ]).fit(frame)
        parameters = dict(window_seconds=1., hop_seconds=.2, min_packets=12, max_gap_seconds=.25)
        bundle = dict(pipeline=pipeline, features=list(MOTION_FEATURES),
                      metadata=dict(experiment='synthetic-export-test', fast_parameters=parameters))
        source = Path(directory)/f'selected_{covariance}.joblib'
        joblib.dump(bundle, source)
        return source, frame, parameters

    def load_module(self, path):
        spec = importlib.util.spec_from_file_location('test_exported_gmm', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_export_selected_results_for_all_gmm_covariances(self):
        with tempfile.TemporaryDirectory() as directory:
            for kind in ('tied', 'diag', 'full', 'spherical'):
                with self.subTest(covariance=kind):
                    source, frame, parameters = self.fitted_bundle(directory, kind)
                    output = Path(directory)/f'inference_{kind}.py'
                    report = export_gmm(source, output, feature_frame=frame)
                    module = self.load_module(output)
                    self.assertEqual(report['covariance_type'], kind)
                    self.assertEqual(report['feature_rows'], len(frame))
                    self.assertTrue(report['labels_identical'])
                    self.assertLess(report['max_probability_error'], 1e-10)
                    self.assertEqual(module.PROVENANCE['metadata']['fast_parameters'], parameters)
                    self.assertEqual(module.FEATURES, MOTION_FEATURES)
                    self.assertTrue(output.with_name(output.stem+'_verification.json').is_file())
                    self.assertNotIn('import sklearn', output.read_text())
                    result = predict_collection_batches(batches(seconds=2), module)
                    self.assertTrue(result['settings_match_training'])
                    self.assertEqual(result['window_parameters'], parameters)
                    self.assertTrue(all(row['inference_mode'] == 'training_window_settings' for row in result['windows']))

    def test_export_without_feature_csv_verifies_missing_value_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _, _ = self.fitted_bundle(directory)
            report = export_gmm(source, Path(directory)/'inference.py')
            self.assertEqual(report['feature_rows'], 0)
            self.assertEqual(report['verification_rows'], len(MOTION_FEATURES)+3)

    def test_lambda_export_preserves_only_the_marked_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            source, frame, _ = self.fitted_bundle(directory, 'full')
            template = Path(directory)/'lambda_function.py'
            template.write_text("obsolete_weights = True\n# AWS Lambda / DynamoDB Streams integration\n"
                                "def lambda_handler(event, context):\n    return predict_records(event)\n")
            report = export_gmm(source, template, feature_frame=frame, lambda_template=template)
            module = self.load_module(template)
            self.assertFalse(hasattr(module, 'obsolete_weights'))
            self.assertEqual(module.lambda_handler([], None), [])
            self.assertIn('lambda_adapter_sha256', report)
            self.assertEqual(module.COEFFICIENTS['model']['covariance_type'], 'full')

    def test_export_handles_exact_collector_clock_without_driver_wrapping(self):
        with tempfile.TemporaryDirectory() as directory:
            source, frame, _ = self.fitted_bundle(directory)
            output = Path(directory)/'inference.py'
            export_gmm(source, output, feature_frame=frame)
            module = self.load_module(output)
            origin = 2**53 + 1
            packets = [dict(timestamp_us=origin+i*50_000, data=[1,2,3,4]*32,
                            len=128, first_word=0) for i in range(41)]
            rows = module.predict_input(packets, kind='raw')
            self.assertEqual(rows[0]['window_start_timestamp_us'], origin)
            self.assertEqual(rows[0]['sample_timestamps_us'], [origin+i*50_000 for i in range(20)])
            packets[-1]['timestamp_us'] = 0
            with self.assertRaisesRegex(ValueError, 'clock reset/out-of-order'):
                module.predict_input(packets, kind='raw')

    def test_failed_verification_preserves_the_existing_model(self):
        with tempfile.TemporaryDirectory() as directory:
            source, frame, _ = self.fitted_bundle(directory)
            output = Path(directory)/'inference.py'
            output.write_text('existing inference artifact')
            with patch('export_gmm._verify_export', side_effect=AssertionError('mismatch')):
                with self.assertRaisesRegex(AssertionError, 'mismatch'):
                    export_gmm(source, output, feature_frame=frame)
            self.assertEqual(output.read_text(), 'existing inference artifact')

    def test_export_rejects_missing_training_window_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _, _ = self.fitted_bundle(directory)
            bundle = joblib.load(source)
            del bundle['metadata']['fast_parameters']
            joblib.dump(bundle, source)
            with self.assertRaisesRegex(ValueError, 'window settings used for training'):
                export_gmm(source, Path(directory)/'inference.py')

    def test_export_filters_mixed_radio_modes_and_emits_train_mapped_presence(self):
        with tempfile.TemporaryDirectory() as directory:
            source, frame, _ = self.fitted_bundle(directory)
            bundle = joblib.load(source)
            bundle['metadata']['input_filter'] = {'sig_mode': '1'}
            bundle['metadata']['state_presence_mapping'] = {'0': 'empty', '1': 'occupied'}
            joblib.dump(bundle, source)
            output = Path(directory)/'inference.py'
            export_gmm(source, output, feature_frame=frame)
            module = self.load_module(output)
            samples = [s for item in batches(seconds=2) for s in item['samples']]
            origin = samples[0]['timestamp_us']
            records = [dict(data=s['csi_raw'], len=128, local_timestamp=s['timestamp_us']-origin,
                            first_word=int(s['first_word_invalid']), sig_mode=1) for s in samples]
            mixed = [item for row in records for item in (row, dict(row, sig_mode=0))]
            actual, expected = module.predict_input(mixed), module.predict_input(records)
            self.assertEqual([r['state'] for r in actual], [r['state'] for r in expected])
            self.assertTrue(all(r['presence_label'] in ('empty', 'occupied') for r in actual))
            with self.assertRaisesRegex(ValueError, 'matching the trained radio format'):
                module.predict_input([dict(row, sig_mode=2) for row in records])
            packets = batches(seconds=2)
            unverified = predict_collection_batches(packets, module)
            self.assertFalse(unverified['windows'])
            self.assertEqual(unverified['captures'][0]['status'], 'unsupported_radio_format')
            for item in packets:
                for sample in item['samples']:
                    sample['sig_mode'] = 1
            self.assertTrue(predict_collection_batches(packets, module)['windows'])


if __name__ == '__main__':
    unittest.main()
