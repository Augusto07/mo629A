"""Write a standalone inference model from an explicitly selected fitted GMM.

Run with a Python environment containing numpy, pandas, joblib and sklearn.
Analysis fits/selects the bundle first. This exporter does not train or select
a winner. The generated module includes that bundle's window settings, feature
order, fitted preprocessing and GMM coefficients; inference needs only NumPy.
"""
from pathlib import Path
import ast
import hashlib
import json
import pprint
import tempfile

import joblib
import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture


RUNTIME = '''
import numpy as np


def read_records(source):
    """Accept CSV, JSON/JSONL paths, a record dict, or a list of dicts.

    JSON may be a record, an array, or {"records": [...]} / {"data": [...]}.
    CSI's data field may be a native integer array or its CSV JSON string.
    """
    if isinstance(source, (str, Path)):
        text = Path(source).read_text(encoding='utf-8-sig').strip()
        if not text:
            return []
        if text[0] in '[{':
            try:
                source = json.loads(text)
            except json.JSONDecodeError:
                source = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            import io
            source = list(csv.DictReader(io.StringIO(text)))
    if isinstance(source, dict):
        for key in ('records', 'rows', 'packets', 'data'):
            if isinstance(source.get(key), list) and all(isinstance(r, dict) for r in source[key]):
                source = source[key]
                break
        else:
            source = [source]
    if not isinstance(source, (list, tuple)) or not all(isinstance(r, dict) for r in source):
        raise ValueError('Expected a record object, array of record objects, or CSV/JSON/JSONL file')
    return [dict(row) for row in source]


def _matrix(values):
    if hasattr(values, "loc"):
        values = values.loc[:, FEATURES].to_numpy(dtype=float)
    x = np.asarray(values, dtype=float)
    if x.ndim == 1:
        x = x.reshape(1, -1)
    if x.ndim != 2 or x.shape[1] != len(FEATURES):
        raise ValueError(f"Expected rows with {len(FEATURES)} features in FEATURES order")
    return x


def impute(values):
    """Replace missing/nonfinite values with the fitted training medians."""
    x = _matrix(values).copy()
    return np.where(np.isfinite(x), x, np.asarray(COEFFICIENTS['imputer']['statistics_']))


def filter_variance(values):
    return np.asarray(values, dtype=float)[:, COEFFICIENTS['variance']['support']]


def scale(values):
    c = COEFFICIENTS['scaler']
    return (np.asarray(values, dtype=float) - np.asarray(c['mean_'])) / np.asarray(c['scale_'])


def transform(values):
    return scale(filter_variance(impute(values)))


def weighted_log_prob(values):
    """Evaluate the selected GMM's Gaussian densities in transformed space."""
    z = transform(values)
    c = COEFFICIENTS['model']
    means = np.asarray(c['means_'])
    precision_chol = np.asarray(c['precisions_cholesky_'])
    kind = c['covariance_type']
    differences = z[:, None, :] - means
    if kind == 'tied':
        transformed = z[:, None, :] @ precision_chol - means @ precision_chol
        log_det = np.log(np.diag(precision_chol)).sum()
    elif kind == 'full':
        transformed = np.einsum('nkd,kde->nke', differences, precision_chol)
        log_det = np.log(np.diagonal(precision_chol, axis1=1, axis2=2)).sum(axis=1)
    elif kind == 'diag':
        transformed = differences * precision_chol
        log_det = np.log(precision_chol).sum(axis=1)
    elif kind == 'spherical':
        transformed = differences * precision_chol[:, None]
        log_det = z.shape[1] * np.log(precision_chol)
    else:
        raise ValueError(f'Unsupported covariance type: {kind}')
    squared = np.sum(transformed ** 2, axis=2)
    return (-0.5 * (z.shape[1] * np.log(2 * np.pi) + squared)
            + log_det + np.log(np.asarray(c['weights_'])))


def score_samples(values):
    logs = weighted_log_prob(values)
    maximum = logs.max(axis=1)
    return maximum + np.log(np.exp(logs - maximum[:, None]).sum(axis=1))


def predict_proba(values):
    logs = weighted_log_prob(values)
    logs -= logs.max(axis=1, keepdims=True)
    probabilities = np.exp(logs)
    return probabilities / probabilities.sum(axis=1, keepdims=True)


def predict(values):
    return weighted_log_prob(values).argmax(axis=1)


def features_from_capture(path):
    """Decode CSI and extract the training-configured fast window features."""
    selected = PROVENANCE['metadata'].get('input_filter')
    source = path
    if selected:
        source = [row for row in read_records(path)
                  if all(str(row.get(name, '')).strip() == str(value) for name, value in selected.items())]
        if len(source) < 2:
            raise ValueError('Capture has fewer than two packets matching the trained radio format')
    time, channel, metadata = read_capture(source)
    timestamps = metadata.pop('sample_timestamps_us')
    rows = extract_features(time, channel, **PROVENANCE['metadata']['fast_parameters'])
    for row in rows:
        row.update(metadata)
        row['session_id'] = Path(path).stem if isinstance(path, (str, Path)) else 'capture'
        row['window_start_timestamp_us'] = timestamps[0] + round(row['window_start_s'] * 1e6)
        row['window_end_timestamp_us'] = timestamps[0] + round(row['window_end_s'] * 1e6)
        indices = np.flatnonzero((time >= row['window_start_s']) & (time < row['window_end_s']))
        row['sample_timestamps_us'] = [timestamps[index] for index in indices]
    return rows


def predict_capture(path):
    """Return all complete windows, retaining rejected windows as unknown."""
    rows = features_from_capture(path)
    return predict_records(rows)


def predict_records(rows):
    rows = [dict(row) for row in rows]
    for index, row in enumerate(rows):
        missing = set(FEATURES) - row.keys()
        if missing:
            raise ValueError(f'Feature record {index}: missing fields {sorted(missing)}')
    good = [row for row in rows if str(row.get('quality_ok', True)).strip().lower() in ('true', '1', 'yes')]
    for row in rows:
        row.update(state=None, log_likelihood=None, status='insufficient_data')
        if 'state_presence_mapping' in PROVENANCE['metadata']:
            row['presence_label'] = None
        for k in range(len(COEFFICIENTS['model']['weights_'])):
            row[f'membership_{k}'] = None
    if good:
        x = [[float(row[name]) if row[name] is not None and str(row[name]).strip() else np.nan
              for name in FEATURES] for row in good]
        labels, probabilities, scores = predict(x), predict_proba(x), score_samples(x)
        for row, label, probability, score in zip(good, labels, probabilities, scores):
            row.update(state=int(label), log_likelihood=float(score), status='ok')
            mapping = PROVENANCE['metadata'].get('state_presence_mapping')
            if mapping:
                row['presence_label'] = mapping[str(int(label))]
            row.update({f'membership_{k}': float(p) for k, p in enumerate(probability)})
    return rows


def predict_input(source, kind='auto'):
    """Predict from file or in-memory records; infer raw CSI vs feature fields."""
    rows = read_records(source)
    if not rows:
        return []
    if kind not in ('auto', 'raw', 'features'):
        raise ValueError('kind must be auto, raw, or features')
    if kind == 'auto':
        if all(set(FEATURES).issubset(row) for row in rows):
            kind = 'features'
        elif all({'data', 'local_timestamp', 'len', 'first_word'}.issubset(row)
                 for row in rows if row.get('type', 'CSI_DATA') == 'CSI_DATA') and any(
                     'local_timestamp' in row for row in rows):
            kind = 'raw'
        else:
            raise ValueError('Cannot infer input schema: expected CSI packet fields or all FEATURES')
    return predict_capture(rows) if kind == 'raw' else predict_records(rows)


if __name__ == '__main__':
    import argparse
    import csv
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='CSV, JSON or JSONL containing raw CSI packets or feature records')
    parser.add_argument('--output', type=str, help='Optional output CSV')
    parser.add_argument('--raw', action='store_true', help='Input is a raw CSI capture; output includes features and rejected windows')
    parser.add_argument('--kind', choices=['auto', 'raw', 'features'], default='auto')
    args = parser.parse_args()
    results = predict_input(args.input, kind='raw' if args.raw else args.kind)
    if args.output and results:
        if Path(args.output).suffix.lower() == '.json':
            def clean(value):
                if isinstance(value, dict):
                    return {k: clean(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [clean(v) for v in value]
                if isinstance(value, float) and not np.isfinite(value):
                    return None
                return value
            Path(args.output).write_text(json.dumps(clean(results), indent=2, allow_nan=False), encoding='utf-8')
        else:
            with open(args.output, 'w', newline='', encoding='utf-8') as target:
                writer = csv.DictWriter(target, fieldnames=list(dict.fromkeys(k for r in results for k in r)))
                writer.writeheader()
                writer.writerows(results)
    labels = [r['state'] for r in results if r['status'] == 'ok']
    print(json.dumps({'windows': len(results), 'accepted': len(labels), 'rejected': len(results)-len(labels),
                      'state_counts': np.bincount(np.asarray(labels, dtype=int), minlength=len(COEFFICIENTS['model']['weights_'])).tolist()}, indent=2))
'''


def _native(value):
    """Keep NumPy scalars nested in sklearn fitted attributes out of literals."""
    if isinstance(value, np.ndarray):
        return _native(value.tolist())
    if isinstance(value, np.generic):
        return _native(value.item())
    if isinstance(value, dict):
        return {key: _native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native(item) for item in value]
    return value


def export_gmm(bundle_path, output_path, *, feature_frame=None, raw_captures=(), lambda_template=None):
    """Export the selected trusted-local bundle and verify before replacement.

    feature_frame may be a CSV path or a DataFrame of analysis results. Its
    quality-passing rows supplement deterministic missing/extreme-value probes.
    Optional serial captures verify raw extraction with the bundle's settings.
    lambda_template retains the source after its unique AWS integration marker;
    it may name output_path to update a self-contained Lambda module in place.
    No existing inference module is replaced unless numerical verification passes.
    """
    root = Path(__file__).resolve().parent
    source = Path(bundle_path).resolve()
    output = Path(output_path).resolve()
    if output.suffix.lower() != '.py':
        raise ValueError('Inference output must be a .py module')
    bundle = joblib.load(source)
    pipeline = bundle['pipeline']
    if [name for name, _ in pipeline.steps] != ['imputer', 'variance', 'scaler', 'model']:
        raise ValueError('Unexpected pipeline stages')
    imputer, variance, scaler, model = [stage for _, stage in pipeline.steps]
    if not isinstance(model, GaussianMixture):
        raise ValueError('Selected result must contain a fitted GaussianMixture')
    features = list(bundle['features'])
    if not features or len(set(features)) != len(features):
        raise ValueError('Bundle must specify a nonempty unique feature order')
    if (model.covariance_type not in ('tied', 'full', 'diag', 'spherical') or
            imputer.strategy != 'median' or imputer.add_indicator or
            not scaler.with_mean or not scaler.with_std or
            len(imputer.statistics_) != len(features) or not np.isfinite(imputer.statistics_).all()):
        raise ValueError('Exporter requires fitted median imputation without dropped/indicator features, variance selection, standard scaling and a GMM')
    # These are the settings actually used when fitting, not notebook overrides
    # applied to the previous model during exploratory inference.
    from collection_pipeline import resolve_window_parameters
    from types import SimpleNamespace
    try:
        resolve_window_parameters(SimpleNamespace(PROVENANCE={'metadata': bundle['metadata']}))
    except KeyError as error:
        raise ValueError('Selected bundle must record the feature window settings used for training') from error
    coefficients = {}
    for name, stage in pipeline.steps:
        coefficients[name] = {key: _native(value)
                              for key, value in vars(stage).items()
                              if key.endswith('_') and not key.startswith('_')}
    coefficients['variance']['support'] = variance.get_support().tolist()
    coefficients['model']['covariance_type'] = model.covariance_type
    try:
        source_name = source.relative_to(root).as_posix()
    except ValueError:
        source_name = source.as_posix()
    provenance = {'source': source_name,
                  'bundle_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                  'metadata': _native(bundle['metadata'])}
    # Freeze the actual parser and feature implementation into the artifact.
    # AST selection keeps pandas and dataset/annotation dependencies out.
    data_source = (root / 'csi_dataset.py').read_text(encoding='utf-8')
    parser_node = next(node for node in ast.parse(data_source).body
                       if isinstance(node, ast.FunctionDef) and node.name == 'read_capture')
    parser_source = ast.get_source_segment(data_source, parser_node)
    parser_source = parser_source.replace(
        "with Path(path).open(newline='', encoding='utf-8-sig') as stream:\n        for row in csv.DictReader(stream):",
        "if True:\n        for row in read_records(path):")
    parser_source = parser_source.replace("row.get('type')", "row.get('type', 'CSI_DATA')")
    parser_source = parser_source.replace("values = json.loads(row['data'])",
        "values = json.loads(row['data']) if isinstance(row['data'], str) else row['data']")
    parser_source = parser_source.replace("group = (row.get('mac'), row.get('channel'), row.get('sig_mode', row.get('rx_format')),",
        "group = (str(row.get('mac')), str(row.get('channel')), str(row.get('sig_mode', row.get('rx_format'))),")
    parser_source = parser_source.replace("row.get('bandwidth'), len(values))", "str(row.get('bandwidth')), len(values))")
    data_runtime = ('\nfrom pathlib import Path\nimport csv\nimport json\n'
                    + (root / 'csi_features.py').read_text(encoding='utf-8')
                    + '\n' + parser_source + '\n')
    module_source = ('"""Exported CSI GMM. NumPy only; accepts raw CSI or extracted features in CSV/JSON/JSONL.\n'
                      'States are GMM components; optional presence labels come from training metadata.\n'
                      'Component membership is not calibrated occupancy confidence.\n"""\n'
                      + 'FEATURES = ' + repr(features) + '\n\n'
                      + 'PROVENANCE = ' + pprint.pformat(provenance, sort_dicts=False, width=100) + '\n\n'
                      + 'COEFFICIENTS = ' + pprint.pformat(coefficients, sort_dicts=False, width=100)
                      + '\n' + data_runtime + '\n' + RUNTIME)
    adapter_source = None
    if lambda_template is not None:
        template = Path(lambda_template).read_text(encoding='utf-8-sig')
        marker = '# AWS Lambda / DynamoDB Streams integration'
        if template.count(marker) != 1:
            raise ValueError('Lambda template must contain exactly one AWS integration marker')
        adapter_source = template[template.index(marker):]
        module_source += '\n\n' + adapter_source
    if feature_frame is None:
        x = pd.DataFrame(columns=features, dtype=float)
    else:
        frame = pd.read_csv(feature_frame) if isinstance(feature_frame, (str, Path)) else feature_frame
        good = (frame.quality_ok.astype(str).str.lower().isin(('true', '1', 'yes'))
                if 'quality_ok' in frame else np.ones(len(frame), dtype=bool))
        x = frame.loc[good, features].replace([np.inf, -np.inf], np.nan)
    probes = np.tile(np.asarray(imputer.statistics_), (len(features) + 3, 1))
    for index in range(len(features)):
        probes[index, index] = np.nan
    probes[-3] = np.nan
    probes[-2:] += np.array([-1000, 1000])[:, None]
    check = pd.DataFrame(np.vstack([x.to_numpy(dtype=float), probes]), columns=features)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Stage directly beside the output. On Windows, TemporaryDirectory creates
    # a private ACL; moving its child out would retain that ACL and lock the
    # exported module to the exporting account instead of repository users.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='gmm-export-',
                                     suffix='.py', dir=output.parent, delete=False) as stream:
        staged = Path(stream.name)
    try:
        staged.write_text(module_source, encoding='utf-8')
        report = _verify_export(staged, pipeline, check, len(x), source_name, raw_captures,
                                bundle['metadata']['fast_parameters'], features)
        # Publish only the verified model. Keep the report beside this artifact,
        # so exporting a different result does not overwrite historical reports.
        staged.replace(output)
    finally:
        staged.unlink(missing_ok=True)
    report.update(output=str(output), window_parameters=bundle['metadata']['fast_parameters'],
                  model_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    if adapter_source is not None:
        report['lambda_adapter_sha256'] = hashlib.sha256(adapter_source.encode('utf-8')).hexdigest()
    output.with_name(output.stem + '_verification.json').write_text(
        json.dumps(report, indent=2), encoding='utf-8')
    return report


def _verify_export(path, pipeline, check, feature_rows, source, raw_captures, parameters, features):
    import importlib.util
    spec = importlib.util.spec_from_file_location('exported_csi_gmm', path)
    standalone = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(standalone)
    z = pipeline[:-1].transform(check)
    np.testing.assert_allclose(standalone.transform(check), z, rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(standalone.predict(check), pipeline.predict(check))
    expected_probability = pipeline.predict_proba(check)
    expected_density = pipeline.steps[-1][1].score_samples(z)
    np.testing.assert_allclose(standalone.predict_proba(check), expected_probability, rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(standalone.score_samples(check), expected_density, rtol=1e-10, atol=1e-10)
    report = dict(source=source, feature_rows=feature_rows, verification_rows=len(check),
                  covariance_type=pipeline.steps[-1][1].covariance_type,
                  labels_identical=True,
                  max_probability_error=float(np.max(np.abs(standalone.predict_proba(check)-expected_probability))),
                  max_log_likelihood_error=float(np.max(np.abs(standalone.score_samples(check)-expected_density))),
                  max_log_likelihood_relative_error=float(np.max(
                      np.abs(standalone.score_samples(check)-expected_density)/np.maximum(1, np.abs(expected_density)))))
    raw_results = []
    from csi_dataset import read_capture
    from csi_features import extract_features
    for capture in raw_captures:
        rows = standalone.predict_capture(capture)
        time, channel, _ = read_capture(capture)
        expected = pd.DataFrame(extract_features(time, channel, **parameters))
        actual = pd.DataFrame(rows)
        assert len(actual) == len(expected)
        if not len(actual):
            continue
        np.testing.assert_array_equal(actual.quality_ok, expected.quality_ok)
        np.testing.assert_allclose(actual[features], expected[features],
                                   rtol=1e-12, atol=1e-12, equal_nan=True)
        good = actual.quality_ok
        if good.any():
            np.testing.assert_array_equal(actual.loc[good, 'state'].astype(int),
                                          pipeline.predict(expected.loc[good, features]))
        assert actual.loc[~good, 'state'].isna().all()
        raw_results.extend(rows)
    report.update(raw_windows_verified=len(raw_results),
                  raw_accepted=sum(r['quality_ok'] for r in raw_results),
                  raw_features_match=True if raw_captures else None,
                  raw_labels_identical=True if raw_captures else None)
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', help='Selected fitted .joblib bundle saved by the analysis pipeline')
    parser.add_argument('--output', default=str(Path(__file__).with_name('standalone_gmm.py')),
                        help='Inference .py module to write after verification')
    parser.add_argument('--features', help='Optional feature CSV from the selected analysis run')
    parser.add_argument('--raw-capture', action='append', default=[],
                        help='Optional serial CSI CSV for raw-feature verification; repeat as needed')
    parser.add_argument('--lambda-template', help='Keep the marked AWS adapter from this file in the exported module')
    args = parser.parse_args(argv)
    report = export_gmm(args.bundle, args.output, feature_frame=args.features,
                        raw_captures=args.raw_capture, lambda_template=args.lambda_template)
    print(json.dumps(report, indent=2))
    print('Exported:', report['output'])


if __name__ == '__main__':
    main()
