"""slo-burn-tuner: stress-test SLO burn-rate alert policies before you ship them.

Runs every scenario through (a) the Google SRE Workbook multi-window
multi-burn-rate policy and (b) a naive static-threshold alert, writes a
scorecard, per-scenario charts, and ready-to-deploy Prometheus rules.
"""
import logging
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

from scenarios import build_scenarios, BUDGET_RATIO, SLO
from policy import WORKBOOK_POLICY, evaluate, naive_fires, episodes, rolling_burn

EVIDENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence")

log = logging.getLogger("burntuner")


def setup_logging():
    os.makedirs(EVIDENCE, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(os.path.join(EVIDENCE, "run.log"), mode="w")])


def chart(scenario, res):
    t = np.arange(len(scenario.total)) / 1440.0
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        err_ratio = np.where(scenario.total > 0, scenario.errors / scenario.total, 0)
    ax1.plot(t, 100 * err_ratio, lw=0.5, color="#555")
    ax1.set_ylabel("error ratio (%)")
    ax1.set_yscale("symlog", linthresh=0.01)
    ax1.set_title(f"{scenario.name}: {scenario.description}", fontsize=9)

    ax2.plot(t, rolling_burn(scenario.total, scenario.errors, 60), lw=0.8, label="burn 1h")
    ax2.plot(t, rolling_burn(scenario.total, scenario.errors, 360), lw=0.8, label="burn 6h")
    ax2.axhline(14.4, color="red", ls=":", lw=0.8)
    ax2.axhline(6.0, color="orange", ls=":", lw=0.8)
    ax2.set_yscale("symlog", linthresh=0.5)
    ax2.set_ylabel("burn rate (x)")
    ax2.set_xlabel("day")
    for mask, color, label in [(res["page_mask"], "red", "PAGE"),
                               (res["ticket_mask"], "orange", "TICKET")]:
        if mask.any():
            ax2.fill_between(t, 0, 1, where=mask, transform=ax2.get_xaxis_transform(),
                             alpha=0.25, color=color, label=label)
    ax2.legend(loc="upper right", fontsize=7)
    fig.tight_layout()
    path = os.path.join(EVIDENCE, f"{scenario.name}.png")
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def prometheus_rules():
    """Emit the winning policy as Prometheus alerting rules."""
    def expr(rule):
        w = {5: "5m", 30: "30m", 60: "1h", 120: "2h", 360: "6h", 1440: "1d", 4320: "3d"}
        return (f"(job:slo_errors:ratio_rate{w[rule.long_min]} / {BUDGET_RATIO}) > {rule.factor} "
                f"and (job:slo_errors:ratio_rate{w[rule.short_min]} / {BUDGET_RATIO}) > {rule.factor}")

    rules = {"groups": [{"name": "slo-burn-rate", "rules": [
        {"alert": f"ErrorBudgetBurn_{r.severity}_{r.long_min}m",
         "expr": expr(r),
         "for": "2m",
         "labels": {"severity": r.severity},
         "annotations": {"summary":
             f"Error budget burning >{r.factor}x over {r.long_min}m and {r.short_min}m "
             f"(SLO {SLO * 100:.1f}%)"}}
        for r in WORKBOOK_POLICY]}]}
    path = os.path.join(EVIDENCE, "prometheus_rules.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(rules, f, sort_keys=False, width=100)
    return path


def main():
    setup_logging()
    log.info("slo-burn-tuner: SLO=%.1f%%, budget ratio=%.4f, policy=%s",
             SLO * 100, BUDGET_RATIO, WORKBOOK_POLICY)
    scenarios = build_scenarios()
    rows = []
    for sc in scenarios:
        res = evaluate(sc, WORKBOOK_POLICY)
        naive = naive_fires(sc.total, sc.errors)
        naive_eps = episodes(naive)
        naive_ttd = None
        if sc.incident_start is not None:
            hits = np.flatnonzero(naive[sc.incident_start:])
            naive_ttd = int(hits[0]) if len(hits) else None
        png = chart(sc, res)
        log.info("scenario=%-16s should_page=%-5s pages=%d tickets=%d ttd=%s ttd_page=%s "
                 "budget_at_detect=%s naive_pages=%d naive_ttd=%s chart=%s",
                 sc.name, sc.should_page, res["page_episodes"], res["ticket_episodes"],
                 res.get("ttd_min"), res.get("ttd_page_min"),
                 f"{res['budget_burned_pct']:.1f}%" if "budget_burned_pct" in res else "-",
                 naive_eps, naive_ttd, os.path.basename(png))
        rows.append((sc, res, naive_eps, naive_ttd))

    # ---- scorecard ----
    def fmt(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "MISSED"

    lines = ["# slo-burn-tuner scorecard", "",
             f"SLO 99.9% / 30d. Policy: Google SRE Workbook multi-window multi-burn-rate "
             f"vs naive `burn>10x over 5m` threshold.", "",
             "| scenario | should page | workbook pages | tickets | TTD (any) | TTD (page) | "
             "budget burned at detect | naive pages | naive TTD |",
             "|---|---|---|---|---|---|---|---|---|"]
    verdicts = []
    for sc, res, naive_eps, naive_ttd in rows:
        lines.append(
            f"| {sc.name} | {sc.should_page} | {res['page_episodes']} | "
            f"{res['ticket_episodes']} | {fmt(res.get('ttd_min'), 'm')} | "
            f"{fmt(res.get('ttd_page_min'), 'm')} | "
            f"{res.get('budget_burned_pct', float('nan')):.1f}% | {naive_eps} | "
            f"{fmt(naive_ttd, 'm')} |"
            if sc.incident_start is not None else
            f"| {sc.name} | {sc.should_page} | {res['page_episodes']} | "
            f"{res['ticket_episodes']} | - | - | - | {naive_eps} | - |")
        if sc.should_page:
            ok = res.get("ttd_min") is not None
            verdicts.append((sc.name, "detected" if ok else "MISSED"))
        else:
            ok = res["page_episodes"] == 0
            verdicts.append((sc.name, "quiet" if ok else f"{res['page_episodes']} false pages"))

    lines += ["", "## Verdicts", ""]
    lines += [f"- **{name}**: {verdict}" for name, verdict in verdicts]
    report = os.path.join(EVIDENCE, "report.md")
    with open(report, "w") as f:
        f.write("\n".join(lines) + "\n")

    rules_path = prometheus_rules()
    log.info("wrote %s and %s", report, rules_path)
    for name, verdict in verdicts:
        log.info("VERDICT %-16s %s", name, verdict)
    log.info("done")


if __name__ == "__main__":
    main()
