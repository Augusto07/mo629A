# CSI modeling and analysis workspace

Updated from the current `E:/IOT/esp-csi` working tree on 2026-11-03.
The analysis source is `drafts/modeling_and_analysis`; the serial capture helper
also includes the current router example's `main(argv=None)` interface.
This folder is self-contained: captures, manifests, notebooks, local modules,
fitted models, and reports resolve here.

## Open a notebook

- `csi_amplitude_phase.ipynb`: amplitude/phase plots, quality checks, features,
  and the feature dashboard for the original recording.
- `csi_modeling.ipynb`: editable change-detection and unsupervised pipelines.
- `csi_classification.ipynb`: supervised presence/count pipelines; requires
  genuine labels and independent training groups.
- `csi_unsupervised_20261025.ipynb`: executed comparison on two occupied-room
  recordings, including sampling coverage, temporal purges, and frozen GMM.

In VS Code select the existing ESP-IDF Python 3.12 environment:

```text
E:\Espressif\tools\python\v6.1\venv\Scripts\python.exe
```

Run cells in order. The notebooks find this directory when launched here or
from the `mo629A` repository root. They also support the original project's
`drafts/modeling_and_analysis` location. Setup cells print the interpreter and
selected workspace/capture path. Historical cell outputs retain their original
execution paths; rerunning updates them to this workspace.

## Dependencies and checks

From this directory, using the intended Python:

```powershell
python -m pip install -r requirements.txt
python -m unittest test_csi_features.py test_csi_modeling.py test_standalone_gmm.py
```

`requirements-notebook.txt` and `requirements-modeling.txt` retain the smaller
dependency groups. `requirements-lock.txt` is the original Windows Python 3.12
analysis environment snapshot; use it when reproducing saved sklearn bundles.
The standalone model requires only NumPy at inference time.

## Current models and results

- `csi_features.py`: windowed features and sampling quality checks.
- `csi_dataset.py`: capture loading, signed/unsigned 32-bit timestamp recovery,
  annotations, causal joins, and leakage checks.
- `csi_models.py`: change detection, unsupervised/supervised comparisons,
  evaluation, and versioned model persistence.
- `capture_csi.py`: timed serial capture to this folder's `captures/`.
- `standalone_gmm.py`: frozen NumPy implementation with embedded coefficients,
  preprocessing, raw CSI parsing, and CSV/JSON/JSONL input.
- `export_gmm.py`: writes a new NumPy inference module from an explicitly selected
  fitted analysis bundle, including its feature order, preprocessing, window
  settings and GMM coefficients. It verifies equivalence before replacing an
  artifact; fitting and model selection happen in analysis, not in the exporter.
- `lambda-function.py`: DynamoDB Stream adapter for decrypted collector batches
  with `samples`, `csi_raw`, and `timestamp_us` fields.
- `lambda-function copy.py`: earlier adapter for raw CSV-shaped packets or
  extracted feature rows; preserved as a separate variant.

The active local inference model was retrained on the user-labeled November 3
empty/occupied pair. It is `gmm_2_full`, with fitted preprocessing and an
experimental training-derived state mapping (0 empty, 1 occupied). Its final
within-recording temporal test balanced accuracy is 61.4%, so this is not a
validated general presence detector. See `reports/latest_presence_model.json`
for artifacts and the run's `RESULTS.md`. Lambda remains unchanged.

The historical occupied-only experiment model is `gmm_2_tied`, saved under
`experiments/occupied_pair_20261025/runs/20261026T012619746575Z/models/`.
Both recordings are occupied. Its states describe clusters; they do not label
empty/occupied rooms or person counts. The experiment uses chronological
partitions within both recordings. It does not establish independent-session
accuracy, and its final test partition remains unevaluated.
See [experiment results](experiments/occupied_pair_20261025/RESULTS.md).

Run frozen inference without fitting a new model:

```powershell
python standalone_gmm.py captures/csi_20261025_200543.csv --kind raw --output predictions.json
```

`standalone_gmm_verification.json` records agreement with the saved sklearn
pipeline across feature/probe rows and both raw captures. The prediction CSVs
and fitted artifacts are preserved with their provenance.

## Captures, annotations, and collection

Run the saved 10-minute COM4 collection script from the repository root:

```powershell
& "E:\Espressif\tools\python\v6.1\venv\Scripts\python.exe" .\modeling_and_analysis\collect_com4_10min.py
```

Defaults are COM4, 921600 baud and 600 seconds, timed from the first valid CSI
packet. It prints progress every 30 seconds and saves a timestamped CSV,
`.status.json` and `.summary.json` in `captures/`. Filenames use UTC-3. The
summary includes packet count, acquisition span, measured packet rate, gaps,
timestamp resets and the CSV hash. Use `--port`, `--baud`, `--seconds`, `--wait`
or `--output` to override defaults. It does not flash or deliberately reset the
board. Only one process can capture from the same serial port at a time.
Use `--delay 300 --presence empty` to wait five minutes before an empty-room
recording; the label is user-declared and is stored in the summary.

To update inference weights from an empty/occupied recording pair:

```powershell
python retrain_presence_gmm.py --occupied captures/occupied.csv --empty captures/empty.csv --wait-for-empty
```

`--wait-for-empty` waits for the collector's completed ten-minute empty summary.
The workflow keeps one common radio format, chooses a sampling profile by
coverage, fits preprocessing on training data only, and uses chronological
60/20/20 partitions with temporal purges. It compares two-component GMMs using
validation data, maps states to user-provided empty/occupied contexts using
training labels, and evaluates the selected model once on the final time split.
It backs up the prior model and exports the verified selected weights to
`standalone_gmm.py`. Run artifacts and annotations live under
`experiments/presence_pair_20261103/runs/`; `reports/latest_presence_model.json`
points to the latest completed update. Two recordings do not establish
independent-session presence accuracy or person counts. Lambda is unchanged.

`captures/` contains the original recording and the three October 25 captures.
The general `dataset_manifest.csv` still describes the original recording;
the occupied-pair experiment uses its separate `manifest.csv`. `labels.csv`
and `events.csv` remain empty until ground truth is supplied. New notebook
runs write reports/models under UTC run-ID subfolders.

The firmware in this repository's `ESP32-CSI` directory collects continuously
at a requested 100 Hz (restored original default), with small FIFO uploads and a bounded RAM queue. Capture
pauses only when all buffers fill. Full batches are attempted once; failures
and power loss can leave missing data. See the router example's `BATCH_POST.md`.

For local analysis of decrypted DynamoDB CSV exports, open
`csi_collection_inference.ipynb`. Its shared `collection_pipeline.py` buffers
packets across uploads using exact 64-bit acquisition timestamps. All four
window/quality parameters are editable in `WINDOW_PROFILES`; the local default
follows the active model's training settings. The short 1-second profile remains
an exploratory comparison. Reports include the selected
settings, batch boundaries, missing sequences, real gaps, and trailing windows.
Assignments under changed settings are marked exploratory.
Run `python -m unittest test_collection_pipeline.py` for transport-boundary
equivalence, clock precision, missing uploads and session isolation checks.
This notebook performs inference rather than fitting; use `retrain_presence_gmm.py`
to update weights from labeled capture pairs. Format-specific models require
matching AP/channel/bandwidth/length and PHY mode metadata; an absent `sig_mode`
in collection batches is unverified and receives no state prediction.

To turn newly fitted/selected analysis results into a new inference artifact:

```powershell
python export_gmm.py path/to/selected.joblib --features path/to/features_and_splits.csv --output models/selected_gmm.py
```

The feature CSV is optional. The exporter supports tied, diagonal, full and
spherical GMM covariance. It uses the window settings saved with the selected
bundle, rather than copying exploratory overrides onto old coefficients. The
collection notebook includes an optional export cell; select the new artifact
with `MODEL_FILENAME` when ready to run inference.

To update the self-contained Lambda module while preserving its marked adapter,
run from this directory (select the fitted bundle and feature CSV explicitly):

```powershell
python export_gmm.py path/to/selected.joblib --features path/to/features_and_splits.csv --lambda-template lambda-function.py --output lambda-function.py
```

`lambda-function.py` now embeds the latest empty/occupied model. Its adapter
normalizes `bandwidth_mhz` (20/40) to ESP bandwidth codes (0/1), preserves
`sig_mode` (or the `rx_format` alias), and separates captures by PHY mode.
Exact 64-bit `timestamp_us` values and optional UTC receipt anchors are preserved.
Missing or mismatched radio metadata produces `capture_issues` with
`unsupported_radio_format`, without assigning presence or raising a model-format
exception. Inputs with no complete window report `too_short`.
Upload boundaries can be crossed within one invocation.

Existing uploads without PHY mode cannot be verified against this trained model.
The firmware JSON in `ESP32-CSI` now includes `sig_mode`; build and flash that
source, and ensure ingestion preserves the field, to supply it on future uploads.
No Lambda deployment or board flashing was performed for this compatibility fix.

The separate firmware in `E:/IOT/esp-csi/collection_script` collects continuously
and sends encrypted HTTPS batches. Decrypt and validate those envelopes with
the collector's ingestion code before passing their inner sample records to
`lambda-function.py`. That adapter processes each invocation independently;
it does not retain a rolling packet buffer across stream invocations. A batch
must contain enough time coverage for the configured feature windows. Serial
sample output is disabled by default in the collector and must be enabled for
`capture_csi.py` to receive local CSI rows.

See [MODELING_GUIDE.md](MODELING_GUIDE.md) for dataset/pipeline editing and current
inference formats, and [MODELING_PLAN.md](MODELING_PLAN.md) for experiment design.
