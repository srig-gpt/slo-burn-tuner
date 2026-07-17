"""Burn-rate alert policy evaluation over per-minute traces."""
import numpy as np

from scenarios import BUDGET_RATIO


class Rule:
    """Multi-window burn-rate rule: fire when burn rate over BOTH the long and
    short window exceeds `factor`. Short window makes alerts reset quickly."""

    def __init__(self, long_min, short_min, factor, severity):
        self.long_min = long_min
        self.short_min = short_min
        self.factor = factor
        self.severity = severity  # "page" or "ticket"

    def __repr__(self):
        return (f"{self.severity}: burn>{self.factor}x over "
                f"{self.long_min}m & {self.short_min}m")


# Google SRE Workbook recommended policy for a 30d SLO window.
WORKBOOK_POLICY = [
    Rule(60,   5,    14.4, "page"),    # 2% of 30d budget in 1h
    Rule(360,  30,   6.0,  "page"),    # 5% of 30d budget in 6h
    Rule(1440, 120,  3.0,  "ticket"),  # 10% of 30d budget in 24h
    Rule(4320, 360,  1.0,  "ticket"),  # slow, steady burn
]


def rolling_burn(total, errors, window):
    """Burn rate (error ratio / budget ratio) over a trailing window, per minute."""
    ct = np.concatenate([[0], np.cumsum(total)])
    ce = np.concatenate([[0], np.cumsum(errors)])
    n = len(total)
    idx = np.arange(1, n + 1)
    lo = np.maximum(idx - window, 0)
    wt = ct[idx] - ct[lo]
    we = ce[idx] - ce[lo]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(wt > 0, we / wt, 0.0)
    return ratio / BUDGET_RATIO


def fires(total, errors, rule):
    """Boolean array: does this rule fire at each minute?

    The first long_min minutes are masked out: a partially-filled window
    inflates the burn rate and produces phantom alerts at trace start.
    """
    long_burn = rolling_burn(total, errors, rule.long_min)
    short_burn = rolling_burn(total, errors, rule.short_min)
    mask = (long_burn > rule.factor) & (short_burn > rule.factor)
    mask[:rule.long_min] = False
    return mask


def naive_fires(total, errors, factor=10.0, window=5):
    """Baseline everyone starts with: single short window, static threshold."""
    mask = rolling_burn(total, errors, window) > factor
    mask[:window] = False
    return mask


def episodes(fire_mask):
    """Count distinct alert episodes (rising edges)."""
    f = fire_mask.astype(np.int8)
    return int(np.sum((f[1:] == 1) & (f[:-1] == 0)) + (f[0] == 1))


def evaluate(scenario, policy):
    """Score a policy against one scenario. Returns dict of metrics."""
    page_mask = np.zeros(len(scenario.total), dtype=bool)
    ticket_mask = np.zeros(len(scenario.total), dtype=bool)
    for rule in policy:
        mask = fires(scenario.total, scenario.errors, rule)
        if rule.severity == "page":
            page_mask |= mask
        else:
            ticket_mask |= mask

    result = {"scenario": scenario.name,
              "should_page": scenario.should_page,
              "page_episodes": episodes(page_mask),
              "ticket_episodes": episodes(ticket_mask),
              "page_mask": page_mask,
              "ticket_mask": ticket_mask}

    detect_mask = page_mask | ticket_mask
    start = scenario.incident_start
    if start is not None:
        hits = np.flatnonzero(detect_mask[start:])
        result["ttd_min"] = int(hits[0]) if len(hits) else None
        page_hits = np.flatnonzero(page_mask[start:])
        result["ttd_page_min"] = int(page_hits[0]) if len(page_hits) else None
        # incident errors accumulated by detection time, as % of the 30d budget
        # (trace is 7 days; scale to a 30d-equivalent budget)
        if len(hits):
            t = start + hits[0]
            budget_30d = BUDGET_RATIO * np.sum(scenario.total) * 30.0 / 7.0
            result["budget_burned_pct"] = (
                100.0 * np.sum(scenario.errors[start:t + 1]) / budget_30d)
    else:
        result["false_pages"] = result["page_episodes"]
    return result
