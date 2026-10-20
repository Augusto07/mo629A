# Running and modifying the CSI models

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

From this example directory, using the ESP-IDF interpreter:

```powershell
python -m unittest test_csi_features.py test_csi_modeling.py
python -m pip check
```

Tests cover timestamp/interval leakage, causal long-window joins, synthetic
distribution shifts, CUSUM resets, label rejection, grouped classification,
training-only transforms, model save/load, and feature-order preservation.
Synthetic tests exercise implementation; they are not real occupancy validation.
