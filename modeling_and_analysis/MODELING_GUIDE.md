# Running and modifying the CSI models

## Continuous collection in small uploads

The repository firmware requests 100 Hz (restored original default), captures during uploads, and pauses
only when its bounded RAM queue fills. Upload batches default to 20 samples.
No collection timer is used; failed uploads get one attempt and are discarded.

Use `csi_collection_inference.ipynb` for exported collection records. The shared
local `collection_pipeline.py` decodes the CSV, preserves 64-bit acquisition
timestamps, and buffers packets across batches into configurable windows. Edit
`WINDOW_PROFILES` and `ACTIVE_PROFILE` in the notebook: the local default follows
the selected model's training settings. The exploratory short profile uses a
1-second window, 0.2-second hop, 12-packet minimum and 0.25-second maximum gap,
including edges. All four values may be overridden through
`predict_collection_batches(batches, model, parameters=...)` or
`CaptureWindowBuffer(model, parameters=...)`. Minimum packet count must be at
least 3; time settings must be positive and representable in whole microseconds.

The pipeline isolates sessions/radio formats and reports unfinished trailing
windows. Receipt time does not replace acquisition time. Inference does not
refit coefficients. Results with modified settings carry
`inference_mode=exploratory_window_override`; changing coverage does not establish
accuracy under the new observation duration. Validate or retrain before relying
on those assignments. Each report records actual parameters and training settings.

The Lambda adapter now normalizes collector bandwidth units, preserves PHY mode
and 64-bit acquisition clocks, and reports incompatible captures in `capture_issues`.
Use the exporter's `--lambda-template lambda-function.py --output lambda-function.py`
options to update its embedded weights while retaining the AWS integration.
It still requires a complete window within one invocation; it does not persist
packets between invocations. Missing `sig_mode` is unverified, not assumed to be
the trained mode. The firmware source now includes this field in JSON uploads;
existing device firmware must be updated before it can transmit the added field.

Run `python -m unittest test_collection_pipeline.py` for the new local checks.
The historical occupied-pair model produced 55 accepted windows on the reference
CSV at `E:\Downloads\results (1).csv` using the short profile. A newly selected
format-specific model can reject that export if its radio format differs or
its PHY mode is not provided. Missing observation time is never imputed.

Use the ESP-IDF Python interpreter:

```text
E:\Espressif\tools\python\v6.1\venv\Scripts\python.exe
```

Install `requirements-modeling.txt` with that interpreter if needed. In VS Code,
select that interpreter as the notebook kernel and run the cells in order.

## Notebooks

- `csi_amplitude_phase.ipynb`: original signal plots and feature inspection.
- `csi_modeling.ipynb`: dataset loading, reference change detection, unsupervised
  pipeline comparison, metrics, model inspection, and saved model artifacts.
- `csi_classification.ipynb`: separate supervised presence/count classification.

The modeling notebook runs on the existing single capture using a clearly
marked chronological exploration. It leaves a purge between partitions and
does not claim performance on independent sessions. Change detection is skipped
until genuine reference sessions are designated. Classification is skipped
until labels and independent training groups exist. No labels are fabricated.

## Prepare captures and annotations

Add raw capture files to `dataset_manifest.csv`; paths are relative to the
manifest. Use one row per `(session_id, link_id)` and one appearance of each
capture. All links from a session must have the same split.

| Column | Meaning |
|---|---|
| session_id | Independent recording identifier. |
| capture_file | Raw CSV path, e.g. `captures/<filename>.csv`. |
| split | `unassigned`, `train`, `validation`, or `test`. |
| reference | `true` only for intentionally recorded stable reference conditions. |
| room_id / placement_id / day | Context for grouped evaluation and generalization tests. |
| link_id | Router-receiver link identifier, retained for extension to more links. |
| notes | Firmware settings, activity, environmental changes, and other context. |

The provided row has unknown occupancy and reference=false. Fill its context
only with observations you actually have. Do not retroactively infer occupancy
from its features. Capture multiple sessions for each class, including seated
occupants, and reserve entire test sessions before comparing candidates.

`labels.csv` is optional until supervised learning. Each interval records
`session_id,start_s,end_s,person_count,activity,notes`; times are seconds from
the first valid packet. Count must be a nonnegative integer or blank. Activity
can describe empty/seated/moving, while count defines the presence target.
Do not overlap intervals within a session. Partial/transition windows do not
receive classification labels. Count classes are 0 / 1 / 2 / 3+, not an exact
count above two. Room-specific low/medium/high categories require explicit
count/capacity boundaries and a separately evaluated label mapping.

`events.csv` stores `session_id,time_s,event,notes`. Annotate changes completely
in evaluated sessions before interpreting event precision/recall. Without
annotations, event metrics remain unavailable rather than treating every alarm
as a false positive.

For change models, provide distinct stable-reference training and validation
sessions; threshold calibration uses only reference validation windows. The
reference need not mean empty, so its alarm-rate metric is described as alarms
per reference hour rather than an occupancy false-positive rate.

## Modify the pipelines

Each notebook contains actual sklearn Pipeline objects; no estimator factories
hide their steps. Edit or append entries in:

- `CHANGE_PIPELINES`: covariance estimators supporting `mahalanobis`.
- `UNSUPERVISED_PIPELINES`: clustering estimators; `predict` enables new-window
  evaluation. sklearn HDBSCAN is supported as a training-only comparator.
- `CLASSIFIER_PIPELINES`: sklearn-compatible classifiers; probabilities enable
  average precision and optional confidence rejection.

Every candidate is cloned before fitting. Change imputation, scaling, PCA,
hyperparameters, or estimator in these lists. For example, a classifier entry
can be added directly after importing the estimator:

```python
from sklearn.svm import SVC
CLASSIFIER_PIPELINES.append({
    "name": "svc_rbf",
    "pipeline": Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("variance", VarianceThreshold()),
        ("scaler", StandardScaler()),
        ("model", SVC(C=1.0, kernel="rbf", class_weight="balanced")),
    ]),
})
```

This SVC example has no probability output; probability-dependent metrics are
therefore unavailable. Do not enable an estimator's internal random calibration
split as a substitute for a leakage-safe grouped calibration procedure.

`FEATURE_COLUMNS` is an explicit allowlist. Add PHASE_FEATURES or SLOW_FEATURES
for ablations. Metadata, quality values, and labels cannot silently enter X.
Selecting slow features adds their complete trailing dependency to label/split
checks and requires slow-window sampling quality as well as fast-window quality.
Training features missing in their entirety cause a visible error; remove such
features or collect usable data rather than inventing an imputed signal.

## Add metrics and interpret results

Comparison functions return a metrics DataFrame and a dictionary of fitted
pipelines/results. The notebooks expose `EXTRA_CHANGE_METRICS`,
`EXTRA_UNSUPERVISED_METRICS`, and `EXTRA_CLASSIFICATION_METRICS` dictionaries of
named scoring callables. Import your sklearn metric and add a callable; each
receives the context described beside that dictionary. Undefined metrics remain
blank and a failed custom metric includes a note rather than breaking other candidates.

For example:

```python
from sklearn.metrics import davies_bouldin_score
EXTRA_UNSUPERVISED_METRICS["davies_bouldin"] = (
    lambda context: davies_bouldin_score(context["X_train"], context["train_labels"])
)
```

Only use this example when at least two nontrivial clusters exist; noise labels
need an explicit policy. The default silhouette implementation excludes noise.

Compare BIC/log likelihood only for GMM candidates in the same transformed
feature space. Silhouette is descriptive cluster separation, not occupancy
accuracy. Seed stability ARI describes random initialization, not robustness to
a new room. Validation count ARI requires actual labels and does not give
cluster IDs a count interpretation. A high value does not establish a reliable
real-time occupancy mapping.

Supervised CV keeps groups intact and skips folds that cannot train every
training class. Validation metrics and descriptive importance are calculated
separately. Bootstrap intervals resample the configured independent groups and
require at least three; correlated windows are not independent replicates.

`RUN_FINAL_TEST=False` is the default in both notebooks. Freeze model/feature/
threshold choices before enabling it. Final predictions use the frozen fitted
pipeline; they do not refit on test data. Poor-quality windows remain unknown.

Reports are written under `reports/<UTC run ID>/`. Selected pipelines and JSON
metadata are saved under `models/<UTC run ID>/`, preserving earlier runs. Their
bundles include feature order and sklearn/Python versions. Use only trusted
local joblib files. `predict_bundle` applies the saved feature order and rejects
poor quality; `frozen_change_trace` applies a saved reference without updating it.

## Verification

From this modeling directory, using the ESP-IDF interpreter:

```powershell
python -m unittest test_csi_features.py test_csi_modeling.py test_standalone_gmm.py
python -m pip check
```

Tests cover timestamp/interval leakage, causal long-window joins, synthetic
distribution shifts, CUSUM resets, label rejection, grouped classification,
training-only transforms, model save/load, and feature-order preservation.
Synthetic tests exercise implementation; they are not real occupancy validation.

## Current occupied-pair experiment and frozen inference

`csi_unsupervised_20261025.ipynb` uses the separate manifest in
`experiments/occupied_pair_20261025/`, with the first 60% of each recording for
training, the next 20% for validation, and purges at boundaries. Both recordings
are occupied; counts and interval-level occupancy labels are unknown. The final
20% remains locked. The selected `gmm_2_tied` has two components with shared
covariance. See that experiment's `RESULTS.md` for sampling acceptance and
selection metrics. Its state IDs have no occupancy/count interpretation.

The loader recovers valid signed representations of the firmware's uint32
microsecond counter before unwrapping. Clock resets/out-of-order packets and
mixed capture formats still require separate captures. The regression suite
covers signed timestamps and counter wrap.

`standalone_gmm.py` embeds the saved preprocessing and fitted coefficients;
inference needs NumPy, with no sklearn or joblib dependency. It accepts raw CSI
or features from CSV, JSON, JSONL, or Python dictionaries/lists through
`predict_input(source, kind='auto')`. Raw packets use `data`, `local_timestamp`,
`len`, and `first_word`; feature rows use the names in `FEATURES`. Quality-failing
windows retain an unknown state. Use `--kind raw` or `--kind features` to specify
the input schema explicitly:

```powershell
python standalone_gmm.py captures/csi_20261025_200543.csv --kind raw --output predictions.json
```

`export_gmm.py` writes a new standalone inference model from a fitted bundle
explicitly selected from analysis results. It no longer chooses a bundle by
filename order or assumes the old occupied-pair experiment. First fit/compare
models using the desired extraction settings, then save the selected result
with `save_bundle`, recording those settings in `metadata['fast_parameters']`.

```powershell
python export_gmm.py path/to/selected.joblib --features path/to/features_and_splits.csv --output models/selected_gmm.py
```

Or call `export_gmm(bundle_path, output_path, feature_frame=results_frame)` from
Python. The feature frame/CSV is optional; missing-value/extreme-value probes
are always checked. Repeat `--raw-capture path/to/capture.csv` to additionally
verify raw feature extraction. Tied, diagonal, full and spherical covariance
are supported with fitted median imputation, variance filtering and scaling.

The new module embeds the selected coefficients, feature order, preprocessing,
training window settings and source-bundle hash. The exporter verifies NumPy
transforms, predictions, probabilities and likelihood against sklearn before
replacing the output. A separate `<output_stem>_verification.json` is written
beside each artifact. No fitting happens during export. The collection notebook
has an optional export cell, and `MODEL_FILENAME` selects the artifact used for
inference. A newly trained short-window bundle makes its matching short-window
settings the inference defaults; the old model need not remain the selected one.
Lambda and historical inference artifacts are not changed by preparing this workflow.

The current collector sends encrypted envelopes. The model consumes decrypted
inner records, not the encrypted payload. `lambda-function.py` converts inner
`samples` entries (`csi_raw`, `timestamp_us`, and radio metadata) to raw model
packets and groups them by device/session/link/format within the invocation.
For Lambda packaging, name the module `lambda_function.py` and configure
`lambda_function.lambda_handler`. The separate `lambda-function copy.py`
variant expects raw packet rows or feature records. Neither variant stores a
rolling packet buffer across invocations, so short batches can produce no
5-second windows. Serial capture requires enabling collector serial output.
