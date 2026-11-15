# Literature Survey — Draft (verify every citation before submitting)

> I wrote this from memory, without being able to open the papers here. The titles, authors and
> venues are ones I am confident exist, but **check each one (Google Scholar / the publisher page)
> and fix any detail** before it goes in your report. Then read at least the abstract and
> conclusion of each paper and rewrite the "Relevance" lines in your own words.

## 1. Log parsing (turning raw lines into templates)
**He, Zhu, Zheng, Lyu — "Drain: An Online Log Parsing Approach with Fixed Depth Tree", IEEE ICWS 2017.**
Parses logs online using a fixed-depth tree keyed on message length and leading tokens, then merges by token similarity.
*Relevance:* SignalDesk's `clustering.py` follows the same idea (bucket by token count + first token, merge above a similarity threshold, wildcard the differing tokens), in a simplified form.

**Zhu, He, He, Liu, Zheng, Lyu — "Tools and Benchmarks for Automated Log Parsing", ICSE-SEIP 2019.**
Compares many log parsers on a common benchmark; Drain performed well on accuracy and speed.
*Relevance:* justifies choosing a Drain-style parser over heavier methods.

## 2. Log anomaly detection
**Xu, Huang, Fox, Patterson, Jordan — "Detecting Large-Scale System Problems by Mining Console Logs", ACM SOSP 2009.**
Early work that parses console logs into features and applies PCA to detect abnormal behaviour.
*Relevance:* motivates automatic detection from logs instead of manual inspection.

**Du, Li, Zheng, Srikumar — "DeepLog: Anomaly Detection and Diagnosis from System Logs through Deep Learning", ACM CCS 2017.**
Models log sequences with an LSTM to predict the next event and flags deviations.
*Relevance:* a stronger but data-hungry approach; discuss as future work and contrast with SignalDesk's lightweight statistical method that needs no training.

**He, Zhu, He, Lyu — "Experience Report: System Log Analysis for Anomaly Detection", IEEE ISSRE 2016.**
Reviews and compares supervised and unsupervised log anomaly detection methods.
*Relevance:* shows that simple methods can be competitive and that evaluation on labelled data matters.

## 3. Statistical outlier detection
**Iglewicz & Hoaglin — "How to Detect and Handle Outliers" (ASQC Basic References in Quality Control, Vol. 16), 1993.**
Introduces the modified z-score using the median and MAD, with 3.5 as the usual cut-off.
*Relevance:* this is the exact formula in `anomaly.py` (0.6745 × (x − median) / MAD, threshold 3.5). Median/MAD resist being skewed by earlier incidents, unlike mean/standard deviation.

## 4. Datasets
**Zhu et al. — "Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics", IEEE ISSRE 2023** (arXiv version circulated earlier as "Loghub: A Large Collection of System Log Datasets towards Automated Log Analytics").
Public collection including HDFS, BGL, Thunderbird, OpenStack and more.
*Relevance:* BGL has per-line alert labels, used by `scripts/evaluate_loghub.py`.

## 5. Existing monitoring tools to compare against (use their official docs)
Elastic Stack (Elasticsearch, Logstash, Kibana), Grafana Loki, Graylog, Splunk, Datadog.
Suggested comparison table: setup effort, cost, built-in anomaly detection, resource use, learning curve.

## 6. Gap your project addresses
Large platforms are powerful but heavy and costly for small teams; many open-source dashboards use fixed thresholds. SignalDesk offers a lightweight, self-hosted option with training-free robust anomaly detection, pattern mining and an evaluation harness.
