"""Deterministic incident scenario generator.

Each scenario is a 7-day, per-minute trace of (total requests, failed requests)
for a service with a 99.9% availability SLO. Scenarios are labeled with ground
truth (should the on-call be paged, and when the incident starts) so alert
policies can be scored objectively.
"""
import numpy as np

MIN_PER_DAY = 1440
DAYS = 7
N = DAYS * MIN_PER_DAY
SLO = 0.999
BUDGET_RATIO = 1.0 - SLO  # 0.1% of requests may fail
BACKGROUND_ERR = 0.0002   # 0.2x burn rate background noise
SEED = 20260716


class Scenario:
    def __init__(self, name, description, should_page, incident_start, total, errors):
        self.name = name
        self.description = description
        self.should_page = should_page
        self.incident_start = incident_start  # minute index or None
        self.total = total
        self.errors = errors


def _traffic(rng):
    """Diurnal traffic: ~200 rpm at night, ~2000 rpm at peak."""
    t = np.arange(N)
    daily = 0.5 * (1 + np.sin(2 * np.pi * (t % MIN_PER_DAY) / MIN_PER_DAY - np.pi / 2))
    return rng.poisson(200 + 1800 * daily).astype(np.int64)


def _errors(rng, total, ratio):
    return rng.binomial(total, np.clip(ratio, 0, 1))


def build_scenarios():
    scenarios = []

    def make(name, description, should_page, incident_start, ratio_fn):
        rng = np.random.default_rng(SEED + abs(hash(name)) % 100000)
        total = _traffic(rng)
        ratio = np.full(N, BACKGROUND_ERR)
        ratio_fn(ratio)
        errors = _errors(rng, total, ratio)
        scenarios.append(Scenario(name, description, should_page, incident_start, total, errors))

    day = MIN_PER_DAY

    make("clean_week",
         "No incident, background 0.2x burn noise only. Any page is a false page.",
         False, None, lambda r: None)

    make("fast_burn",
         "Major outage: 8% error ratio (80x burn) for 4h starting day 3, 12:00.",
         True, 3 * day + 720,
         lambda r: r.__setitem__(slice(3 * day + 720, 3 * day + 960), 0.08))

    make("slow_burn",
         "Quiet regression: 0.35% error ratio (3.5x burn) from day 2 onward. "
         "Exhausts the 30d budget in ~8.5 days; must be caught, paging optional.",
         True, 2 * day,
         lambda r: r.__setitem__(slice(2 * day, N), 0.0035))

    make("transient_spike",
         "Bad canary rolled back: 20% errors for 2 minutes at 03:00, day 1. "
         "Burns <0.5% of the 30d budget; paging a human for this is alert fatigue.",
         False, None,
         lambda r: r.__setitem__(slice(1 * day + 180, 1 * day + 182), 0.20))

    make("night_flapping",
         "Nightly cron causes 5% errors for 2 min each hour, 00:00-05:00, low traffic. "
         "Annoying but tiny absolute budget burn; should not page.",
         False, None,
         lambda r: [r.__setitem__(slice(d * day + h * 60, d * day + h * 60 + 2), 0.05)
                    for d in range(DAYS) for h in range(0, 5)])

    make("gradual_ramp",
         "Slow leak: error ratio ramps 0 -> 2% over 12h starting day 4 (memory leak pattern).",
         True, 4 * day,
         lambda r: r.__setitem__(slice(4 * day, 4 * day + 720),
                                 BACKGROUND_ERR + np.linspace(0, 0.02, 720)))

    return scenarios
