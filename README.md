# slo-burn-tuner

Stress-test your SLO burn-rate alert policy **before** you ship it to Prometheus.

## The problem

Most teams copy the multi-window multi-burn-rate alert rules from the Google SRE
Workbook, paste them into Prometheus, and find out in production whether they
page too much (fatigue) or too late (missed budget burn). There is no cheap way
to answer "would this policy have paged me for *that* kind of incident, and how
fast?" without living through the incident.

## What this does

`slo-burn-tuner` replays a library of realistic, labeled incident scenarios —
fast burn, slow burn, transient deploy blip, low-traffic night flapping, gradual
ramp, and a clean week — against a burn-rate policy, entirely offline, and scores it:

- **Time-to-detect** for every real incident (any severity, and page severity)
- **Error budget already burned** at the moment of detection
- **False pages** on scenarios where a human should *not* have been woken up
- Side-by-side comparison with the naive `error rate > 10x SLO for 5m` alert
  most teams start with

It then emits the validated policy as ready-to-deploy **Prometheus alerting
rules** (`evidence/prometheus_rules.yaml`).

## Results (this run)

See `evidence/` for the full scorecard (`report.md`), per-scenario charts,
raw run log, and generated rules. Headline from this run:

- Workbook policy: detects all 3 real incidents (fast burn paged in 10 min with
  3.8% of budget burned; slow burn ticketed in 17.5h; gradual ramp paged in
  5.5h), and stays **completely silent** on the clean week, the rolled-back
  canary, and the nightly cron flapping.
- Naive `burn>10x over 5m` alert: **36 needless pages** in one week (the 2-min
  canary blip + all 35 night flaps), 14 flappy pages during the gradual ramp,
  and its only "detection" of the slow burn is a noise fluke 71 hours in.

## Run it

```bash
pip install -r requirements.txt
python run.py
```

Deterministic (fixed seed): you will reproduce the exact numbers in `evidence/`.

## Adapt it

- Change `SLO` / traffic shape in `scenarios.py` to match your service.
- Edit `WORKBOOK_POLICY` in `policy.py` and re-run to tune thresholds.
- Add your own scenario in `build_scenarios()` (e.g. a past incident's shape)
  to make regressions in your alerting policy testable.

## Layout

```
scenarios.py   labeled 7-day incident traces (per-minute good/bad counts)
policy.py      burn-rate math, workbook policy, naive baseline, scoring
run.py         runs everything, writes evidence/ + prometheus_rules.yaml
evidence/      captured output of a real run (log, scorecard, charts, rules)
```
