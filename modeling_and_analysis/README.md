# CSI modeling and analysis workspace

This folder contains independent copies of the analysis notebooks and their
local dependencies. The original example files remain in
`examples/get-started/csi_recv_router`.

## Open a notebook

- `csi_amplitude_phase.ipynb`: CSI amplitude/phase plots, extracted features,
  quality checks, and feature dashboard.
- `csi_modeling.ipynb`: editable change-detection and unsupervised pipelines.
- `csi_classification.ipynb`: separate supervised presence/count pipelines.

In VS Code select the existing ESP-IDF kernel:

```text
E:\Espressif\tools\python\v6.1\venv\Scripts\python.exe
```

Run all cells. The notebooks locate this folder from either this folder or
the repository root. Set an absolute capture path if running from elsewhere.
Local imports, default captures, reports, and new model artifacts use this
workspace. A notebook's first setup cell reports the selected interpreter and
capture/workspace path.

## Dependencies

Python 3.12 is the verified runtime. From this folder, using the intended Python:

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` includes notebook/modeling packages and pyserial for capture.
`requirements-notebook.txt` and `requirements-modeling.txt` retain their smaller
dependency groups. `requirements-lock.txt` records exact analysis-package and
dependency versions from the working Windows ESP-IDF environment, without
copying the interpreter or unrelated ESP-IDF tools. To reproduce that snapshot:

```powershell
python -m pip install -r requirements-lock.txt
```

Local Python modules are included alongside the notebooks:

- `csi_features.py`: windowed feature extraction.
- `csi_dataset.py`: raw capture loading, annotations, causal joins, and split checks.
- `csi_models.py`: evaluation and model persistence helpers.
- `capture_csi.py`: timed serial capture; its default output is this folder's `captures/`.

## Data and results

`captures/` contains the existing raw recording and derived features/plots.
`dataset_manifest.csv`, `labels.csv`, and `events.csv` use paths relative to this
folder. Labels/events are intentionally empty until ground truth is supplied.

`models/` and `reports/` include snapshots of previously generated artifacts.
Historical artifacts preserve their original provenance paths. New notebook
runs write local reports and models under UTC run-ID subfolders. All pipelines
and metric-extension dictionaries remain exposed in the copied notebooks.

See [MODELING_GUIDE.md](MODELING_GUIDE.md) for editing datasets and pipelines and
[MODELING_PLAN.md](MODELING_PLAN.md) for the experiment design.

## Verify the local modules

```powershell
python -m unittest test_csi_features.py test_csi_modeling.py
python -m pip check
```

The existing capture supports exploratory clustering. Reference change detection
requires designated stable reference sessions; supervised evaluation requires
labeled independent sessions. The notebooks report these prerequisites rather
than fabricating occupancy scores.
