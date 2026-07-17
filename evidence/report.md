# slo-burn-tuner scorecard

SLO 99.9% / 30d. Policy: Google SRE Workbook multi-window multi-burn-rate vs naive `burn>10x over 5m` threshold.

| scenario | should page | workbook pages | tickets | TTD (any) | TTD (page) | budget burned at detect | naive pages | naive TTD |
|---|---|---|---|---|---|---|---|---|
| clean_week | False | 0 | 0 | - | - | - | 0 | - |
| fast_burn | True | 1 | 1 | 10m | 10m | 3.8% | 1 | 0m |
| slow_burn | True | 0 | 2 | 1052m | MISSED | 9.9% | 3 | 4261m |
| transient_spike | False | 0 | 0 | - | - | - | 1 | - |
| night_flapping | False | 0 | 0 | - | - | - | 35 | - |
| gradual_ramp | True | 1 | 1 | 329m | 329m | 2.1% | 14 | 253m |

## Verdicts

- **clean_week**: quiet
- **fast_burn**: detected
- **slow_burn**: detected
- **transient_spike**: quiet
- **night_flapping**: quiet
- **gradual_ramp**: detected
