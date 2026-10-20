# CSI change detection, clustering, and occupancy classification

## Objective and scope

Extend the existing feature extractor and notebook with three complementary
models, using scikit-learn in the existing ESP-IDF Python environment. Models
run on the PC first. Firmware deployment is a separate future task.

1. Detect persistent changes relative to a reference signal distribution.
2. Discover recurring signal states without fitting to occupancy labels.
3. Classify occupancy from labeled recordings, first binary, then room fullness.

Unsupervised clusters are not inherently people counts. One moving person can
produce more variation than several seated people. Map clusters to occupancy
only after independent observations support that interpretation; once labels
are used to fit that mapping, the overall system is no longer fully unsupervised.

## 1. Build the dataset and shared processing

- Retain raw CSI and versioned feature CSVs, with a session manifest containing
  session_id, room_id, placement_id, day, source MAC, channel, capture path,
  device/firmware settings, and extraction parameters.
- Store optional ground truth as intervals: start_s, end_s, person_count,
  activity (empty/seated/moving), and notes for doors, fans, pets, and furniture.
  Windows crossing occupancy changes are marked transition or excluded from
  stable-state classification; they remain useful for change-detector evaluation.
- Collect separate empty, one-person seated, one-person moving, and multiple-person
  sessions. Start with counts 0, 1, 2, and 3+ where feasible. Repeat positions,
  activities, and count order across sessions/days so time and activity do not
  act as proxies for occupancy. A practical pilot is 5–10 minutes per condition
  repeated over several sessions; this is a starting protocol, not a sample-size guarantee.
- Keep room/router/receiver placement fixed for the initial experiment. Later
  hold out changed placements and rooms as explicit generalization tests.
- Measure packet gaps and actual rate before increasing feature complexity. The
  current capture has only 18 overlapping windows and only 3 pass the existing
  periodicity checks; it cannot support credible model selection or accuracy claims.
- Add two feature scales: approximately 5-second windows/1-second steps for
  fast changes and 30-second windows/5-second steps for slow structure. Validate
  quality requirements separately for each scale. Slow features must not be
  presented as available before their complete window has arrived.
- Use causal trailing windows and report window_end_s as the availability time.
  Keep window centers for descriptive plots only. Never use future packets in
  a real-time decision or centered smoothing.
- Start from amplitude spread, MAD, CV, packet changes, normalized equivalents,
  correlation, and PCA fractions. Treat raw/relative phase as an ablation rather
  than assuming phase improves classification. Keep periodic features optional.
- Use an explicit feature allowlist: exclude timestamps, filenames, IDs, labels,
  quality flags, packet rate, and gap measurements from the initial predictive
  inputs. Use acquisition-quality fields for gating/reporting, not presence clues.
- Implement preprocessing with Pipeline: training-only SimpleImputer,
  VarianceThreshold, and StandardScaler or RobustScaler where appropriate.
  Exclude unavailable feature families rather than imputing an entire missing
  periodicity signal. Reject poor windows with an explicit unknown/insufficient_data state.
  Do not use the dashboard's whole-recording z-scores as model inputs.

## 2. Add a reference-based change model

Question: has the signal distribution persistently departed from the reference?

- Fit preprocessing and sklearn.covariance.LedoitWolf on designated stable
  reference training recordings. Calculate squared Mahalanobis distances for
  new windows. Shrinkage helps when features are correlated.
- Add a small custom sequential CUSUM layer over the distance score; this is
  application logic, not a built-in sklearn change-point estimator. Expose
  baseline score centering, drift allowance, alarm threshold, reset behavior,
  and persistence/hysteresis in configuration.
- Tune thresholds on separate reference validation recordings for a target
  false-alarm rate per hour. Evaluate annotated arrival/departure/movement
  events with event precision/recall and detection delay measured from when
  the event occurred to when the alarm was available.
- Reset sequential state between sessions and after long data outages. Freeze
  the reference during evaluation; do not silently learn an occupied room as
  the new empty baseline. Recalibration must be explicit and versioned.
- Output distance, accumulated score, change flag, quality status, and alarm
  episodes. Label these as signal changes, not confirmed human presence.

Deliverable: score timeline with thresholds and annotated events, plus event metrics.

## 3. Add unsupervised state discovery

- First baseline: Pipeline(imputation, scaling, optional PCA, GaussianMixture).
  Start with a small component search including one component, diagonal covariance,
  multiple random initializations, and covariance regularization.
- Choose complexity using BIC, held-out session log likelihood, and stability
  across seeds/sessions. Do not force the number of clusters to equal the desired
  number of occupancy classes. PCA is optional and fitted only on training data.
- GMM supplies a cluster assignment, membership probabilities, and a density
  score for new windows. These probabilities describe component membership,
  not calibrated probabilities of human presence or room fullness.
- Compare HDBSCAN offline to discover non-Gaussian states and noise without
  fixing a cluster count. sklearn HDBSCAN is an exploratory comparator here;
  its API does not provide native predict for new windows. Keep GMM as the
  initial model for consistent inference on new captures.
- Optionally fit IsolationForest on known-empty reference sessions as a
  novelty baseline. The estimator is unsupervised, but choosing known-empty
  training data supplies baseline semantics; this is not fully unlabeled discovery.
  A novelty score measures departure from that baseline, not people count.
- Visualize training-fitted PCA projections, cluster timelines, component
  profiles, low-density windows, and assignments on held-out sessions. Report
  missingness, acquisition conditions, and activity by cluster to find confounding.

Path toward fullness:

1. Discover states without occupancy labels; use neutral IDs such as state_0.
2. Compare frozen states with separately observed counts and activities. Determine
   whether clusters represent occupancy, movement, placement, or radio conditions.
3. If associations repeat across sessions, build a separately evaluated mapping
   to room-specific categories: empty / low / medium / high. Define boundaries
   using actual count or count/capacity, not assumed signal-energy ordering.
4. Permit several clusters to map to one occupancy category. Reject ambiguous or
   unfamiliar windows rather than forcing every state into a count class.
5. If a single link does not distinguish occupancy reliably, keep the output as
   activity/state discovery and assess additional transmitter-receiver links.
   Preserve link_id and aligned features to permit that extension later.

Deliverable: state discovery notebook section and frozen inference pipeline;
no automatic occupancy labels until validated against ground truth.

## 4. Add supervised classification

- Stage A: empty versus occupied, ensuring occupied examples include seated,
  minimally moving people. Stage B: 0 / 1 / 2 / 3+ or room-specific fullness
  categories once each has repeated, independent sessions.
- Benchmark DummyClassifier first, then regularized LogisticRegression with
  scaling and RandomForestClassifier with constrained depth/leaf sizes. Consider
  HistGradientBoostingClassifier after the dataset is large enough for a useful
  comparison. Tune a small grid with grouped cross-validation.
- Evaluate class weighting where necessary, using the same held-out splits.
  Include a movement-only baseline to test whether occupancy prediction adds
  information beyond activity.
- For binary presence report PR-AUC, precision/recall, balanced accuracy, and
  false alarms per empty-room hour. For fullness report macro-F1, per-class
  recall, confusion matrix, and ordinal class-distance error. Do not turn a
  coarse 3+ label into an exact-count MAE claim.
- Inspect held-out permutation importance and feature-family ablations.
  Any probability calibration, temporal smoothing, and abstention threshold
  must be fitted/tuned on training/validation sessions, not the final test.

Deliverable: classification comparison, confusion matrices, probability timeline,
and explicit unknown output when quality or calibrated confidence is inadequate.

## 5. Validate without leakage

- Reserve a final test day/session before tuning. Use GroupKFold or
  StratifiedGroupKFold by session_id for development when each class has enough
  independent sessions. Group related sessions by day/placement when required
  by the generalization claim.
- Keep overlapping windows and repeated representations of the same raw time
  interval in one partition. For within-session chronological evaluation, purge
  at least the largest feature-window duration around boundaries, and ensure
  trailing feature dependencies cannot cross a split.
- Fit imputers, scalers, PCA, clustering, thresholds, and classifier parameters
  only on the relevant training partition. Never refit during final evaluation.
- Report uncertainty by resampling sessions rather than individual correlated
  windows. Report performance separately for seated/moving occupants and each
  tested count, along with the fraction of windows rejected for quality.
- Add synthetic tests for known distribution shifts, no-change signals,
  missing-data rejection, feature-order validation, and save/load equivalence.
  Synthetic recovery tests verify implementation, not real-world occupancy accuracy.

## 6. Implementation layout and rollout

- csi_dataset.py: combine feature tables, manifests, interval labels, and grouped splits.
- csi_models.py: preprocessing, reference model/CUSUM, GMM, and classifier pipelines.
- csi_modeling.ipynb: change and clustering sections, with exposed pipeline arrays.
- csi_classification.ipynb: supervised classification in a separate notebook.
  Both use raw captures to build causal features; the original signal-inspection
  notebook remains available.
- dataset_manifest.csv and labels.csv: documented schemas/templates, not invented labels.
- models/: versioned trusted-local joblib bundles and JSON metadata containing
  feature schema, parameters, software versions, training sessions, and thresholds.
- reports/: held-out predictions, scores, quality coverage, and visualizations.

Implement in this order: dataset contract and split checks → change baseline →
unsupervised discovery → labeled binary classification → fullness experiment.
Use the ESP-IDF Python environment and add scikit-learn to modeling requirements
only when implementation starts. Check dependency compatibility with pip check.

The first acceptance gate is successful execution and leakage-safe evaluation;
the later gate is useful performance on independent labeled sessions. Agree on
application-specific false-alarm and delay targets before tuning those targets.

## API references

- [LedoitWolf](https://scikit-learn.org/stable/modules/generated/sklearn.covariance.LedoitWolf.html)
- [GaussianMixture](https://scikit-learn.org/stable/modules/generated/sklearn.mixture.GaussianMixture.html)
- [HDBSCAN](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.HDBSCAN.html)
- [IsolationForest](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html)
- [StratifiedGroupKFold](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html)
- [Data leakage and pipelines](https://scikit-learn.org/stable/common_pitfalls.html)
