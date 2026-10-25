# Depth evaluation

Compares camera-only distance estimates with LiDAR or tape-measured ground truth.
The protocol and decision criteria are in [docs/depth-eval-plan.md](../docs/depth-eval-plan.md).
Standard-library Python only; tested with Python 3.14.7 on Windows 11.

Run every command from this `Evaluation` folder.

## Check that it works

```sh
python -m unittest discover -s tests -v
python -m depth_eval fixture --out artifacts/fixture-report
```

The first command runs the unit tests. The second builds the **synthetic correctness
fixture** and writes a full report to `artifacts/fixture-report/results/report/report.md`
(about 40 seconds). The fixture has planted errors, so the report's numbers are known in
advance: the baseline is 25% too far, `plus10` is 10% too far, `minus20cm` is 0.2 m too
near with one missing prediction, and `relative` is exact after calibration. It is
**not accuracy evidence**.

Output folders must be new or empty; scored runs are never overwritten.

## Evaluate real data

```sh
python -m depth_eval run --dataset DATASET.json --replay REPLAY.json --predictions PREDICTIONS.json --config CONFIG.json --out artifacts/RUN_NAME
```

Start from `config.example.json`. Real runs refuse synthetic inputs and always use 10,000
bootstrap resamples.

## What the command does, in order

1. Fits the relative model's scale on **calibration** scenes only.
2. Scores the calibration, selection, and test splits (`objects.csv` per split).
3. Chooses one method on **selection** scenes only (`selection.json`).
4. Reports on **test** scenes: error metrics, coverage, failure rates, and 95% intervals
   from resampling whole scene groups (`report/`).

Locations, scene groups, and physical objects are assigned to splits together, so the
same place or object never appears in both tuning and test data.
