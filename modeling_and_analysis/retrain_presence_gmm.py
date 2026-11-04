"""Retrain and export a GMM from user-labeled empty and occupied CSI captures.

Uses one common radio format, chronological 60/20/20 splits with temporal purges,
training-only preprocessing and state mapping, validation selection, then one
final test evaluation. Two recordings cannot establish independent-session accuracy.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
import pandas as pd
from sklearn.feature_selection import VarianceThreshold
from sklearn.impute import SimpleImputer
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, f1_score
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from csi_dataset import MOTION_FEATURES, read_capture
from csi_features import extract_features
from csi_models import save_bundle
from export_gmm import export_gmm


PARAMETERS = dict(window_seconds=3., hop_seconds=1., min_packets=12, max_gap_seconds=1.)
SAMPLING_PROFILES = (PARAMETERS, dict(window_seconds=5., hop_seconds=1., min_packets=12, max_gap_seconds=2.))
RADIO_FIELDS = ('mac', 'channel', 'sig_mode', 'bandwidth', 'len')
PRESENCE = {0: 'empty', 1: 'occupied'}


def radio_views(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        header = reader.fieldnames
        groups = {}
        for row in reader:
            if row.get('type') == 'CSI_DATA':
                key = tuple(str(row[name]).strip() for name in RADIO_FIELDS)
                groups.setdefault(key, []).append(row)
    return header, groups


def temporal_splits(frame, duration_s, purge_seconds=5.):
    result = frame.copy()
    a, b = duration_s*.6, duration_s*.8
    result['split'] = 'purged'
    result.loc[result.window_end_s <= a-purge_seconds, 'split'] = 'train'
    result.loc[(result.window_start_s >= a+purge_seconds) &
               (result.window_end_s <= b-purge_seconds), 'split'] = 'validation'
    result.loc[result.window_start_s >= b+purge_seconds, 'split'] = 'test'
    return result


def state_mapping(states, presence):
    """Resolve arbitrary component IDs using training labels only."""
    choices = ({'0': 'empty', '1': 'occupied'}, {'0': 'occupied', '1': 'empty'})
    return max(choices, key=lambda mapping: balanced_accuracy_score(
        presence, mapped_presence(states, mapping)))


def mapped_presence(states, mapping):
    return np.asarray([int(mapping[str(int(state))] == 'occupied') for state in states])


def evaluate(pipeline, frame, mapping):
    states = pipeline.predict(frame[MOTION_FEATURES])
    prediction = mapped_presence(states, mapping)
    return dict(balanced_accuracy=float(balanced_accuracy_score(frame.presence, prediction)),
                f1=float(f1_score(frame.presence, prediction, zero_division=0)),
                confusion_matrix=confusion_matrix(frame.presence, prediction, labels=[0, 1]).tolist(),
                mean_log_likelihood=float(pipeline.score(frame[MOTION_FEATURES]))), states


def fit_candidate(train, validation, covariance_type):
    if train[MOTION_FEATURES].isna().all().any():
        raise ValueError('A selected feature is entirely missing in training')
    pipeline = Pipeline([
        ('imputer', SimpleImputer(strategy='median')), ('variance', VarianceThreshold()),
        ('scaler', StandardScaler()),
        ('model', GaussianMixture(n_components=2, covariance_type=covariance_type,
                                  n_init=10, random_state=42, reg_covar=1e-4, max_iter=500)),
    ]).fit(train[MOTION_FEATURES])
    if not pipeline['model'].converged_:
        raise ValueError('GMM did not converge')
    mapping = state_mapping(pipeline.predict(train[MOTION_FEATURES]), train.presence)
    metrics, _ = evaluate(pipeline, validation, mapping)
    return pipeline, mapping, metrics


def retrain(occupied_path, empty_path, output_root=None, active_model=None):
    root = Path(__file__).resolve().parent
    occupied_path, empty_path = Path(occupied_path).resolve(), Path(empty_path).resolve()
    if occupied_path == empty_path:
        raise ValueError('Empty and occupied recordings must be different files')
    paths = {'empty': empty_path, 'occupied': occupied_path}
    views = {context: radio_views(path) for context, path in paths.items()}
    common = set(views['empty'][1]) & set(views['occupied'][1])
    common = {key for key in common if int(key[-1]) == 128}
    if not common:
        raise ValueError('No common 128-value radio format across the two recordings')
    selected = max(sorted(common), key=lambda key: min(len(views[c][1][key]) for c in paths))
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run = Path(output_root or root/'experiments/presence_pair_20261103/runs')/run_id
    (run/'filtered').mkdir(parents=True)
    (run/'models').mkdir()
    sources, filtered_paths, decoded = [], [], {}
    for presence, context in PRESENCE.items():
        path = paths[context]
        header, groups = views[context]
        filtered = run/'filtered'/f'{context}.csv'
        with filtered.open('w', newline='', encoding='utf-8') as output:
            writer = csv.DictWriter(output, fieldnames=header)
            writer.writeheader()
            writer.writerows(groups[selected])
        time_s, channel, metadata = read_capture(filtered)
        if metadata['malformed_packets']:
            raise ValueError(f'Malformed packets in the selected {context} view')
        if time_s[-1] < 540:
            raise ValueError(f'{context} capture has less than nine minutes of usable time')
        decoded[context] = (time_s, channel)
        filtered_paths.append(filtered)
        sources.append(dict(recording_context=context, presence=presence, source='user',
                            path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            selected_packets=len(time_s), all_packets=sum(map(len, groups.values())),
                            duration_s=float(time_s[-1])))
    sampling_results = []
    for parameters in SAMPLING_PROFILES:
        frames, coverage = [], []
        for presence, context in PRESENCE.items():
            time_s, channel = decoded[context]
            frame = pd.DataFrame(extract_features(time_s, channel, **parameters))
            frame = temporal_splits(frame, time_s[-1])
            frame['session_id'], frame['presence'], frame['recording_context'] = paths[context].stem, presence, context
            frame['source_capture'] = str(paths[context])
            frames.append(frame)
            coverage.append(dict(context=context, complete_windows=len(frame),
                                 accepted_windows=int(frame.quality_ok.sum()),
                                 coverage=float(frame.quality_ok.mean())))
        minimum_coverage = min(item['coverage'] for item in coverage)
        sampling_results.append(dict(parameters=dict(parameters), frames=frames,
                                     coverage=coverage, minimum_coverage=minimum_coverage))
        if minimum_coverage >= .85:
            break
    # Sampling coverage chooses the observation profile, never prediction accuracy.
    chosen_profile = next((item for item in sampling_results if item['minimum_coverage'] >= .85),
                          max(sampling_results, key=lambda item: item['minimum_coverage']))
    parameters, frames, coverage = chosen_profile['parameters'], chosen_profile['frames'], chosen_profile['coverage']
    profile_comparison = [dict(parameters=item['parameters'], coverage=item['coverage']) for item in sampling_results]
    all_rows = pd.concat(frames, ignore_index=True)
    all_rows.replace([np.inf, -np.inf], np.nan, inplace=True)
    splits = {name: all_rows[all_rows.split.eq(name) & all_rows.quality_ok].copy()
              for name in ('train', 'validation', 'test')}
    for name, minimum in (('train', 30), ('validation', 10), ('test', 10)):
        for presence in PRESENCE:
            if splits[name].presence.eq(presence).sum() < minimum:
                raise ValueError(f'Not enough {name} windows for {PRESENCE[presence]}')
    # Enforce raw observation separation, not merely distinct row indices.
    for session in all_rows.session_id.unique():
        for left, right in (('train', 'validation'), ('validation', 'test')):
            earlier = splits[left][splits[left].session_id.eq(session)]
            later = splits[right][splits[right].session_id.eq(session)]
            if earlier.window_end_s.max() > later.window_start_s.min():
                raise AssertionError('Raw feature windows overlap across partitions')
    candidates, fitted = [], {}
    for covariance in ('tied', 'diag', 'full', 'spherical'):
        name = f'gmm_2_{covariance}'
        try:
            pipe, mapping, metrics = fit_candidate(splits['train'], splits['validation'], covariance)
            candidates.append(dict(model=name, status='ok', **metrics))
            fitted[name] = (pipe, mapping)
            print(f'Fitted {name}; validation balanced accuracy={metrics["balanced_accuracy"]:.4f}', flush=True)
        except (ValueError, np.linalg.LinAlgError) as error:
            candidates.append(dict(model=name, status='error', reason=str(error)))
    table = pd.DataFrame(candidates)
    eligible = table[table.status.eq('ok')]
    if eligible.empty:
        raise ValueError('No GMM candidate fitted successfully')
    selected_name = eligible.sort_values(['balanced_accuracy', 'mean_log_likelihood'], ascending=False).iloc[0].model
    pipeline, mapping = fitted[selected_name]
    # Test labels are used only here, after selection/mapping/preprocessing freeze.
    test_metrics, _ = evaluate(pipeline, splits['test'], mapping)
    def relative(path):
        try: return path.relative_to(root).as_posix()
        except ValueError: return str(path)
    metadata = dict(experiment='presence_pair_20261103', fast_parameters=parameters,
                    input_filter=dict(zip(RADIO_FIELDS, selected)),
                    state_presence_mapping=mapping, recording_annotations=sources,
                    training_capture_files=[relative(path) for path in filtered_paths],
                    training_sessions=splits['train'].session_id.unique().tolist(),
                    validation_sessions=splits['validation'].session_id.unique().tolist(),
                    split_mode='Chronological 60/20/20 within each recording with 5-second purges on each boundary side',
                    selection='Validation balanced accuracy with train-only component mapping; validation likelihood breaks ties',
                    sampling_profile_selection='First predefined profile with at least 85% quality coverage in each recording; otherwise highest minimum coverage. No prediction metrics used.',
                    sampling_profile_comparison=profile_comparison,
                    validation_metrics=eligible[eligible.model.eq(selected_name)].iloc[0].to_dict(),
                    final_test_metrics=test_metrics,
                    interpretation='Exploratory presence model from one empty and one occupied recording; temporal holdout only, no independent-session accuracy or person count')
    bundle_path = run/'models'/f'{selected_name}.joblib'
    save_bundle(bundle_path, pipeline, MOTION_FEATURES, metadata)
    all_rows.to_csv(run/'features_and_splits.csv', index=False)
    table.to_csv(run/'candidate_metrics.csv', index=False)
    pd.DataFrame(coverage).to_csv(run/'coverage.csv', index=False)
    pd.DataFrame(sources).to_csv(run/'recordings.csv', index=False)
    predictions = all_rows.copy()
    good = predictions.quality_ok
    predictions['state'], predictions['presence_prediction'] = np.nan, None
    predictions.loc[good, 'state'] = pipeline.predict(predictions.loc[good, MOTION_FEATURES])
    predictions.loc[good, 'presence_prediction'] = [mapping[str(int(x))] for x in predictions.loc[good, 'state']]
    predictions.to_csv(run/'predictions.csv', index=False)
    new_model = run/'models'/'standalone_gmm.py'
    verification = export_gmm(bundle_path, new_model, feature_frame=all_rows, raw_captures=filtered_paths)
    target = Path(active_model or root/'standalone_gmm.py')
    previous = run/'previous'
    previous.mkdir()
    previous_sha = None
    if target.exists():
        previous_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        shutil.copy2(target, previous/target.name)
        old_report = target.with_name(target.stem+'_verification.json')
        if old_report.exists(): shutil.copy2(old_report, previous/old_report.name)
    # Export a second verified artifact to activate the selected weights.
    active_verification = export_gmm(bundle_path, target, feature_frame=all_rows, raw_captures=filtered_paths)
    if previous_sha == active_verification['model_sha256']:
        raise AssertionError('Model artifact did not change')
    report = dict(run_id_utc=run_id, run_directory=str(run), selected_model=selected_name,
                  parameters=parameters, radio_filter=metadata['input_filter'], coverage=coverage,
                  sampling_profile_comparison=profile_comparison,
                  state_presence_mapping=mapping, test_metrics=test_metrics,
                  test_interpretation=metadata['interpretation'],
                  partition_rows={name: len(frame) for name, frame in splits.items()},
                  sources=sources, bundle=str(bundle_path), active_model=str(target),
                  previous_model_sha256=previous_sha, model_sha256=active_verification['model_sha256'],
                  export_verification=verification, lambda_changed=False)
    (run/'run_summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    latest = root/'reports/latest_presence_model.json'
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--occupied', type=Path, required=True)
    parser.add_argument('--empty', type=Path, required=True)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--active-model', type=Path)
    parser.add_argument('--wait-for-empty', action='store_true',
                        help='Wait for a successful full-length empty-capture summary before fitting')
    args = parser.parse_args(argv)
    if args.wait_for_empty:
        occupied_sha = hashlib.sha256(args.occupied.read_bytes()).hexdigest()
        deadline = time.monotonic()+1800
        summary_path = args.empty.with_suffix('.summary.json')
        last_report = 0
        while not summary_path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('Timed out waiting for the empty-room capture')
            if time.monotonic()-last_report >= 30:
                print('Waiting for the completed empty-room capture before model fitting.', flush=True)
                last_report = time.monotonic()
            time.sleep(5)
        summary = json.loads(summary_path.read_text())
        if (summary.get('exit_code') != 0 or summary.get('recording_context') != 'empty' or
                (summary.get('acquisition_span_s') or 0) < 590):
            raise ValueError('The empty-room recording did not complete a usable ten-minute capture')
        if hashlib.sha256(args.occupied.read_bytes()).hexdigest() != occupied_sha:
            raise ValueError('The occupied reference changed while waiting')
    retrain(args.occupied, args.empty, args.output_root, args.active_model)


if __name__ == '__main__':
    main()
