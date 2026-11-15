# Real-world evaluation: Loghub BGL

## Dataset and provenance

- Dataset: `BGL_2k.log`, the 2,000-line labeled sample in the [Loghub BGL dataset](https://github.com/logpai/loghub/tree/374038faa4ca122dd7ca0730372c0b78f76f8597/BGL).
- Source file: [pinned BGL_2k.log](https://github.com/logpai/loghub/blob/374038faa4ca122dd7ca0730372c0b78f76f8597/BGL/BGL_2k.log).
- Dataset description: [Loghub BGL README](https://github.com/logpai/loghub/blob/374038faa4ca122dd7ca0730372c0b78f76f8597/BGL/README.md). A `-` in the first column labels a non-alert line; another value labels an alert line.
- SHA-256: `2a819ea540909db682005c9cf948387a40729b5c2e9f19d430e29ce704825496`.
- The sample has 2,000 parseable lines spanning 2005-06-03 22:42 UTC through 2006-01-03 15:13 UTC. Its timestamps are sparse over this interval; the minute-resolution series therefore contains many empty buckets. It is not the complete BGL corpus and results must not be presented as full-corpus results.

Download the pinned file and reproduce the production-resolution evaluation from the project root:

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/logpai/loghub/374038faa4ca122dd7ca0730372c0b78f76f8597/BGL/BGL_2k.log" `
  -OutFile "BGL_2k.log"
python backend\scripts\evaluate_loghub.py BGL_2k.log --metric errors --bucket-minutes 1
```

The script labels a bucket positive when it contains at least one BGL alert-labeled line. Its default signal is the count of `ERROR`, `FATAL`, `SEVERE`, and `FAILURE` lines, without using the label column as an input feature. It compares a trailing mean threshold with the existing robust median/MAD detector; each prediction is scored against the bucket label. The mean baseline excludes the bucket currently being scored.

## Results

Primary result at the application's one-minute resolution, using the existing robust detector threshold `z >= 3.5`:

| Method | Flagged | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Trailing mean baseline | 24 | 7 | 17 | 118 | 0.292 | 0.056 | 0.094 |
| Robust z-score, errors, 3.5 | 2 | 0 | 2 | 125 | 0.000 | 0.000 | 0.000 |

There are 125 positive minutes in 307,712 one-minute buckets (0.041%). At the default resolution, the detector did not identify any labeled alert minutes. This is a **negative real-data result**: the high synthetic benchmark scores do not generalize to this sparse BGL sample under minute-level error-volume detection.

Bucket-width sensitivity using the same error signal and `z >= 3.5`:

| Bucket width | Method | TP | FP | FN | Precision | Recall | F1 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 min | Trailing mean | 7 | 17 | 118 | 0.292 | 0.056 | 0.094 |
| 1 min | Robust z-score | 0 | 2 | 125 | 0.000 | 0.000 | 0.000 |
| 5 min | Trailing mean | 10 | 12 | 85 | 0.455 | 0.105 | 0.171 |
| 5 min | Robust z-score | 2 | 7 | 93 | 0.222 | 0.021 | 0.038 |
| 15 min | Trailing mean | 10 | 11 | 58 | 0.476 | 0.147 | 0.225 |
| 15 min | Robust z-score | 5 | 10 | 63 | 0.333 | 0.074 | 0.120 |
| 60 min | Trailing mean | 6 | 8 | 43 | 0.429 | 0.122 | 0.190 |
| 60 min | Robust z-score | 8 | 6 | 41 | 0.571 | 0.163 | 0.254 |

Coarser aggregation changes class prevalence (for example, 49 positive hourly buckets out of 5,130) and effective history length. These rows are a sensitivity analysis, not a like-for-like replacement for the default one-minute detector evaluation. Even the best displayed F1 is low, and a single small sample does not justify choosing a new production bucket size.

## Interpretation and next work

The detector's volume-only signal misses alert-labeled minutes when alerts are sparse or are not accompanied by multiple error-severity lines. This dataset does not establish that the anomaly detector is generally effective on operational data. Do not replace these results with the synthetic benchmark or describe the coarser-bucket F1 as production performance.

Next, evaluate the full BGL corpus or another sufficiently large labeled dataset, keep a chronological holdout, and report results by alert category as well as overall. Test message/template and event-sequence signals against the volume-only baseline; do not include the ground-truth label in those features. Report class prevalence and confusion counts alongside precision, recall, and F1.
