"""Evaluation utilities. Estimators and preprocessing are defined in the notebooks."""
from pathlib import Path
import json
import platform

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.decomposition import PCA
from sklearn.metrics import (adjusted_rand_score, average_precision_score,
                             balanced_accuracy_score, confusion_matrix,
                             f1_score, precision_score, recall_score,
                             silhouette_score, classification_report)
from sklearn.model_selection import StratifiedGroupKFold

from csi_dataset import select_features, quality_mask, assert_disjoint, exposure_seconds


def _usable(frame, features, target=None):
    mask = quality_mask(frame, features)
    if target:
        mask &= frame[target].notna() & (frame.label_status == 'stable')
    return frame.loc[mask].copy()


def _score_clusters(x, labels):
    labels = np.asarray(labels)
    keep = labels != -1
    clusters = np.unique(labels[keep])
    if len(clusters) < 2 or len(clusters) >= keep.sum():
        return np.nan
    return float(silhouette_score(np.asarray(x)[keep], labels[keep],
                                  sample_size=min(1000, keep.sum()), random_state=42))


def _extra_metrics(record, registry, context):
    for name, function in (registry or {}).items():
        try:
            record[name] = float(function(context))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            record[name] = np.nan
            record[name+'_note'] = str(error)


def session_mean_interval(values, seed=42, samples=1000):
    """Bootstrap independent session scores, not overlapping windows.

    Returns the mean of session metrics and a percentile interval; at least
    three independent sessions are required. This is not a pooled-window CI.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 3:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    means = rng.choice(values, size=(samples, len(values)), replace=True).mean(axis=1)
    return float(np.mean(values)), *np.quantile(means, [0.025, 0.975]).tolist()


def compare_unsupervised(candidates, train, validation, features, min_rows=6,
                         stability_seeds=(7, 19, 41), extra_metrics=None):
    """Clone editable pipelines; validation metrics never trigger refitting.

    BIC is comparable only for GMMs using the same transformed feature space.
    Membership probabilities are not occupancy probabilities.
    """
    metrics, results = [], {}
    fit_rows, val_rows = _usable(train, features), _usable(validation, features)
    for candidate in candidates:
        name = candidate['name']
        record = dict(model=name, status='skipped', train_rows=len(fit_rows),
                      validation_rows=len(val_rows), representation=candidate.get('representation', 'default'))
        metrics.append(record)
        if len(fit_rows) < min_rows:
            record['reason'] = f'Need at least {min_rows} usable training windows'
            continue
        try:
            pipe = clone(candidate['pipeline'])
            x = select_features(fit_rows, features)
            if x.isna().all().any():
                raise ValueError('Entire training feature missing; remove that feature or collect data')
            pipe.fit(x)
            z = pipe[:-1].transform(x)
            estimator = pipe.steps[-1][1]
            labels = estimator.predict(z) if hasattr(estimator, 'predict') else estimator.labels_
            labels = np.asarray(labels)
            record.update(status='ok', clusters=len(set(labels)-{-1}),
                          train_noise_fraction=float(np.mean(labels == -1)),
                          train_silhouette=_score_clusters(z, labels),
                          transformed_dimensions=z.shape[1])
            if hasattr(estimator, 'bic'):
                record['train_bic'] = float(estimator.bic(z))
            output = dict(pipeline=pipe, train_rows=fit_rows, train_labels=labels,
                          validation_rows=val_rows)
            if len(val_rows) and hasattr(estimator, 'predict'):
                zv = pipe[:-1].transform(select_features(val_rows, features))
                predicted = estimator.predict(zv)
                output['validation_labels'] = predicted
                output['X_validation'] = zv
                record['validation_silhouette'] = _score_clusters(zv, predicted)
                if hasattr(estimator, 'score_samples'):
                    record['validation_log_likelihood'] = float(np.mean(estimator.score_samples(zv)))
                    output['validation_density'] = estimator.score_samples(zv)
                if hasattr(estimator, 'predict_proba'):
                    output['validation_membership'] = estimator.predict_proba(zv)
                # Labels are used only for this external evaluation, never to fit clusters.
                annotated = val_rows.person_count.notna().to_numpy()
                if annotated.sum() >= 2:
                    record['validation_ARI_vs_count'] = adjusted_rand_score(
                        val_rows.person_count.to_numpy()[annotated], predicted[annotated])
            elif len(val_rows):
                record['validation_note'] = 'Estimator has no out-of-sample predict (e.g. sklearn HDBSCAN)'
            # Initialization stability at fixed data, not a generalization metric.
            if 'random_state' in estimator.get_params():
                stability = []
                for seed in stability_seeds:
                    alt = clone(estimator).set_params(random_state=seed)
                    alt.fit(z)
                    alternate = alt.predict(z) if hasattr(alt, 'predict') else alt.labels_
                    stability.append(adjusted_rand_score(labels, alternate))
                record['seed_stability_ARI'] = float(np.mean(stability)) if stability else np.nan
            # Training-fitted visualization only. Not used as additional model input.
            if z.shape[1] >= 2 and len(z) >= 2:
                projection = PCA(n_components=2).fit(z)
                output['train_projection'] = projection.transform(z)
                if len(val_rows):
                    output['validation_projection'] = projection.transform(
                        pipe[:-1].transform(select_features(val_rows, features)))
            _extra_metrics(record, extra_metrics, dict(output, X_train=z, train_labels=labels))
            results[name] = output
        except (ValueError, np.linalg.LinAlgError) as error:
            record.update(status='error', reason=str(error))
    return pd.DataFrame(metrics), results


def covariance_scores(pipe, frame, features):
    x = select_features(frame, features)
    return pipe.steps[-1][1].mahalanobis(pipe[:-1].transform(x))


def cusum_trace(frame, scores, center, scale, allowance=0.5, threshold=8.0,
                reset_gap_s=6.0, clear_fraction=0.25, clear_after=3):
    """One-sided persistent-change score with hysteresis; reset at outages/session changes.

    Invalid rows reset state and produce unknown (NaN). Alarm events are rising
    edges, not every above-threshold overlapping window. Parameters need validation.
    """
    if scale <= 0 or allowance < 0 or threshold <= 0 or reset_gap_s <= 0:
        raise ValueError('Invalid CUSUM scale, allowance, threshold, or reset gap')
    if not 0 <= clear_fraction < 1 or clear_after < 1:
        raise ValueError('Invalid CUSUM hysteresis settings')
    output, state, active, low, previous = [], 0.0, False, 0, None
    for (_, row), score in zip(frame.iterrows(), scores):
        key = (row.session_id, row.get('link_id', ''))
        now = float(row.window_end_s)
        if previous is None or key != previous[0] or now-previous[1] > reset_gap_s or now < previous[1]:
            state, active, low = 0.0, False, 0
        previous = key, now
        if not np.isfinite(score):
            state, active, low = 0.0, False, 0
            output.append(dict(score=score, cusum=np.nan, alarm=False, event=False, status='insufficient_data'))
            continue
        increment = (score-center)/scale - allowance
        state = max(0.0, state+increment)
        # Cap above threshold so a long shift does not accumulate unbounded memory.
        state = min(state, 2*threshold)
        event = not active and state >= threshold
        if event:
            active = True
        low = low+1 if state <= threshold*clear_fraction else 0
        if low >= clear_after:
            active = False
        output.append(dict(score=float(score), cusum=state, alarm=active, event=event, status='ok'))
    return pd.concat([frame.reset_index(drop=True), pd.DataFrame(output)], axis=1)


def match_events(trace, events, tolerance_s=30):
    """One-to-one matching: alarms may follow an event by up to tolerance_s."""
    alarms = trace.loc[trace.event, ['session_id', 'window_end_s']].sort_values('window_end_s')
    relevant = events[events.session_id.isin(trace.session_id.unique())].copy()
    if relevant.empty:
        return dict(event_precision=np.nan, event_recall=np.nan, mean_delay_s=np.nan,
                    event_note='No event annotations; unmatched alarms are not labeled false positives')
    # Only score events inside the evaluated feature-time span for that session.
    evaluated = []
    for _, event in relevant.iterrows():
        session = trace[trace.session_id == event.session_id]
        if session.window_start_s.min() <= event.time_s <= session.window_end_s.max():
            evaluated.append(event)
    if not evaluated:
        return dict(event_precision=np.nan, event_recall=np.nan, mean_delay_s=np.nan,
                    event_note='No annotated events in evaluated span')
    used, delays = set(), []
    for event in sorted(evaluated, key=lambda e: e.time_s):
        for i, alarm in alarms.iterrows():
            delay = alarm.window_end_s-event.time_s
            if i not in used and alarm.session_id == event.session_id and 0 <= delay <= tolerance_s:
                used.add(i)
                delays.append(delay)
                break
    return dict(event_precision=len(delays)/len(alarms) if len(alarms) else 0.0,
                event_recall=len(delays)/len(evaluated),
                mean_delay_s=float(np.mean(delays)) if delays else np.nan,
                matched_events=len(delays), annotated_events=len(evaluated))


def frozen_change_trace(result, frame, features):
    """Use a fitted reference and calibrated threshold without updating either."""
    frame = frame.sort_values(['session_id', 'link_id', 'window_end_s'])
    score = np.full(len(frame), np.nan)
    good = quality_mask(frame, features).to_numpy()
    if good.any():
        score[good] = covariance_scores(result['pipeline'], frame.loc[good], features)
    return cusum_trace(frame, score, result['center'], result['scale'],
                       threshold=result['threshold'], **result['cusum_parameters'])


def run_change_models(candidates, train, validation, features, events, evaluation=None,
                      cusum_parameters=None, false_alarm_target_per_hour=1.0,
                      threshold_grid=(4.0, 8.0, 16.0, 32.0), min_rows=8,
                      event_tolerance_s=30, extra_metrics=None):
    """Fit designated reference/train; choose CUSUM threshold on reference/validation only."""
    options = dict(allowance=0.5, reset_gap_s=6.0, clear_fraction=0.25, clear_after=3)
    options.update(cusum_parameters or {})
    fit_rows = _usable(train[train.reference], features)
    calibration = validation[validation.reference].sort_values(['session_id', 'link_id', 'window_end_s'])
    valid_calibration = _usable(calibration, features)
    evaluate = validation if evaluation is None else evaluation
    evaluate = evaluate.sort_values(['session_id', 'link_id', 'window_end_s'])
    metrics, fitted = [], {}
    for candidate in candidates:
        record = dict(model=candidate['name'], status='skipped', reference_train_rows=len(fit_rows),
                      reference_validation_rows=len(valid_calibration))
        metrics.append(record)
        if len(fit_rows) < min_rows or len(valid_calibration) < min_rows:
            record['reason'] = 'Designate independent stable reference training and validation data in the manifest'
            continue
        try:
            assert_disjoint(fit_rows, valid_calibration, 'session_id')
            pipe = clone(candidate['pipeline'])
            x = select_features(fit_rows, features)
            if x.isna().all().any():
                raise ValueError('An entire reference feature is missing')
            pipe.fit(x)
            reference_scores = covariance_scores(pipe, fit_rows, features)
            center = float(np.median(reference_scores))
            scale = max(float(1.4826*np.median(np.abs(reference_scores-center))), 1e-6)

            def trace_for(frame, threshold):
                score = np.full(len(frame), np.nan)
                good = quality_mask(frame, features).to_numpy()
                if good.any():
                    score[good] = covariance_scores(pipe, frame.loc[good], features)
                return cusum_trace(frame, score, center, scale, threshold=threshold, **options)

            calibration_table = []
            duration = exposure_seconds(valid_calibration)/3600
            for threshold in sorted(threshold_grid):
                trace = trace_for(calibration, threshold)
                calibration_table.append(dict(threshold=threshold,
                    reference_alarm_episodes_per_hour=float(trace.event.sum()/duration) if duration else np.nan))
            eligible = [r for r in calibration_table if r['reference_alarm_episodes_per_hour'] <= false_alarm_target_per_hour]
            if not eligible:
                record.update(reason='No threshold meets reference validation false-alarm target',
                              status='uncalibrated')
                continue
            chosen = eligible[0]
            trace = trace_for(evaluate, chosen['threshold'])
            record.update(status='ok', center=center, scale=scale, **chosen,
                          reference_validation_hours=duration, evaluation_rows=len(trace),
                          quality_coverage=float((trace.status == 'ok').mean()) if len(trace) else np.nan)
            record.update(match_events(trace, events, event_tolerance_s))
            _extra_metrics(record, extra_metrics, dict(trace=trace, pipeline=pipe,
                           calibration=calibration_table, features=features))
            # These are alarms in the chosen reference, not necessarily empty-room alarms.
            fitted[candidate['name']] = dict(pipeline=pipe, trace=trace,
                center=center, scale=scale, threshold=chosen['threshold'],
                cusum_parameters=options, calibration=pd.DataFrame(calibration_table))
        except (ValueError, np.linalg.LinAlgError) as error:
            record.update(status='error', reason=str(error))
    return pd.DataFrame(metrics), fitted


def classification_metrics(y, prediction, probabilities=None, classes=None):
    labels = np.unique(np.r_[y, prediction])
    result = dict(balanced_accuracy=balanced_accuracy_score(y, prediction),
                  macro_f1=f1_score(y, prediction, average='macro', zero_division=0),
                  ordinal_class_distance=float(np.mean(np.abs(np.asarray(y)-prediction))))
    if set(labels).issubset({0, 1}):
        result.update(precision=precision_score(y, prediction, zero_division=0),
                      recall=recall_score(y, prediction, zero_division=0))
        if probabilities is not None and classes is not None and 1 in classes and len(np.unique(y)) > 1:
            result['average_precision'] = average_precision_score(y, probabilities[:, list(classes).index(1)])
    return result


def compare_classifiers(candidates, train, validation, features, target='presence',
                        group_column='session_id', n_splits=3, evaluate_validation=True,
                        extra_metrics=None):
    """Grouped development CV; optional separate validation. Final test is caller controlled."""
    train = _usable(train, features, target)
    validation = _usable(validation, features, target)
    records, results = [], {}
    if group_column in train and train[group_column].astype(str).eq('').any():
        raise ValueError(f'Fill {group_column} to use grouped classification CV')
    for candidate in candidates:
        record = dict(model=candidate['name'], status='skipped', train_rows=len(train),
                      validation_rows=len(validation))
        records.append(record)
        if train[target].nunique() < 2 or train[group_column].nunique() < 2:
            record['reason'] = 'Need labeled training data with >=2 classes and >=2 independent groups'
            continue
        try:
            x = select_features(train, features)
            y = train[target].astype(int).to_numpy()
            if x.isna().all().any():
                raise ValueError('An entire training feature is missing')
            cv = StratifiedGroupKFold(n_splits=min(n_splits, train[group_column].nunique()),
                                      shuffle=True, random_state=42)
            folds = []
            for fit, hold in cv.split(x, y, groups=train[group_column]):
                assert_disjoint(train.iloc[fit], train.iloc[hold], group_column)
                if set(y[fit]) != set(y):
                    continue
                model = clone(candidate['pipeline']).fit(x.iloc[fit], y[fit])
                prediction = model.predict(x.iloc[hold])
                probabilities = model.predict_proba(x.iloc[hold]) if hasattr(model, 'predict_proba') else None
                folds.append(classification_metrics(y[hold], prediction, probabilities,
                                                     getattr(model, 'classes_', None)))
            if not folds:
                record['reason'] = 'No feasible grouped folds; collect more sessions per class'
                continue
            for key in set().union(*(fold.keys() for fold in folds)):
                values = [f[key] for f in folds if key in f and np.isfinite(f[key])]
                record['cv_'+key] = float(np.mean(values)) if values else np.nan
            record['cv_folds'] = len(folds)
            model = clone(candidate['pipeline']).fit(x, y)
            result = dict(pipeline=model, fold_metrics=pd.DataFrame(folds))
            if evaluate_validation and len(validation):
                assert_disjoint(train, validation, group_column)
                xv, yv = select_features(validation, features), validation[target].astype(int).to_numpy()
                prediction = model.predict(xv)
                prob = model.predict_proba(xv) if hasattr(model, 'predict_proba') else None
                record.update({'validation_'+k: v for k, v in classification_metrics(
                    yv, prediction, prob, getattr(model, 'classes_', None)).items()})
                result.update(validation_rows=validation, prediction=prediction, probabilities=prob,
                              confusion=confusion_matrix(yv, prediction),
                              class_report=classification_report(yv, prediction, output_dict=True, zero_division=0))
                sessions = []
                for session in validation[group_column].unique():
                    mask = (validation[group_column] == session).to_numpy()
                    sessions.append(dict(session_id=session, macro_f1=f1_score(
                        yv[mask], prediction[mask], average='macro', labels=np.unique(y), zero_division=0)))
                result['session_metrics'] = pd.DataFrame(sessions)
                mean, lower, upper = session_mean_interval([s['macro_f1'] for s in sessions])
                record.update(validation_session_mean_macro_f1=mean,
                              validation_session_macro_f1_ci_low=lower,
                              validation_session_macro_f1_ci_high=upper)
                negatives = validation[yv == 0]
                if target == 'presence' and len(negatives):
                    # Episode starts include a new session or a gap; duration is interval union.
                    predicted_rows = validation.copy()
                    predicted_rows['prediction'] = prediction
                    episodes = 0
                    for _, group in predicted_rows.groupby(['session_id', 'link_id']):
                        group = group.sort_values('window_end_s')
                        false = ((group[target] == 0) & (group.prediction == 1)).to_numpy()
                        boundary = np.r_[True, np.diff(group.window_end_s) > 6]
                        episodes += np.sum(false & (boundary | ~np.r_[False, false[:-1]]))
                    hours = exposure_seconds(negatives)/3600
                    record['validation_false_positive_episodes_per_empty_hour'] = float(episodes/hours) if hours else np.nan
            record['status'] = 'ok'
            _extra_metrics(record, extra_metrics, dict(result, train_rows=train, target=target))
            results[candidate['name']] = result
        except ValueError as error:
            record.update(status='error', reason=str(error))
    return pd.DataFrame(records), results


def save_bundle(path, pipeline, features, metadata, **extra):
    """Serialize trusted-local models with their feature order and provenance."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    info = dict(metadata, features=list(features), sklearn_version=sklearn.__version__,
                python_version=platform.python_version(), pipeline_repr=str(pipeline))
    joblib.dump(dict(pipeline=pipeline, features=list(features), metadata=info, **extra), path)
    path.with_suffix('.json').write_text(json.dumps(info, indent=2, default=str), encoding='utf-8')


def predict_bundle(bundle, frame):
    x = select_features(frame, bundle['features'])
    good = quality_mask(frame, bundle['features'])
    prediction = np.full(len(frame), np.nan)
    if good.any():
        prediction[good.to_numpy()] = bundle['pipeline'].predict(x.loc[good])
    return prediction
