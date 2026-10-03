"""Edge research framework: does a REAL, cost-adjusted, out-of-sample edge exist?

Principles (enforced in code, not just documented):
  * The ranking metric is OUT-OF-SAMPLE NET EXPECTANCY after MEASURED costs - never accuracy, AUC or win rate.
  * Strict chronological walk-forward with an embargo; several independent OOS windows; thresholds and model choices
    are made on TRAIN/VALIDATION only (walkforward.py).
  * Objective, documented status gates with a multiple-testing correction (evaluate.py).
  * Two model types only: a deterministic RULE and closed-form RIDGE regression on a cost-aware target. No model
    shopping (experiments.py).
  * Every experiment is appended to a registry; an equivalent experiment on the same data is REFUSED, and the
    research of the previous 25 days is seeded into it (registry.py, seeds.py).
  * Nothing here can trade: the best possible outcome is ACCEPTED_FOR_SHADOW.
"""
