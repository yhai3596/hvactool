"""M-VALID validation rig (M1). Leave-units-out ONLY (row-level random splits are
forbidden project-wide); event-level Yuill-Braun five-category scoring.

API pinned by tests/test_m1_valid.py + module instruction (pins, no local freedom):
  leave_units_out_splits(df, unit_col, n_folds=3)
      units sorted lexicographically, split into n_folds CONTIGUOUS groups (ceil
      division) — deterministic and reproducible; returns [(train_idx, test_idx)]
      holding df.index values.
  score_events(preds, truths, match_days=7) -> dict
      anti-double-count matching: truths processed in (unit, day) order; candidates =
      same unit, |day delta| <= match_days, not-yet-consumed preds; pick min |delta|,
      tie -> earlier pred day; each pred consumed at most once. Pair classification:
      same family -> correct; pred family in {None, "no_response"} -> no_response;
      else misdiagnosis. Leftover truths -> missed, leftover preds -> false_alarm.

Dual-baseline comparisons are STUBS until M4 (labeled data) — no speculative logic.
"""
import math

import pandas as pd

CATEGORIES = ("correct", "missed", "false_alarm", "misdiagnosis", "no_response")


def leave_units_out_splits(df: pd.DataFrame, unit_col: str, n_folds: int = 3) -> list:
    """Unit-disjoint folds; every unit appears in exactly one test fold."""
    units = sorted(df[unit_col].unique())
    fold_size = math.ceil(len(units) / n_folds)
    splits = []
    for i in range(n_folds):
        test_units = set(units[i * fold_size:(i + 1) * fold_size])
        in_test = df[unit_col].isin(test_units)
        splits.append((df.index[~in_test], df.index[in_test]))
    return splits


def score_events(preds: pd.DataFrame, truths: pd.DataFrame, match_days: int = 7) -> dict:
    """Event-level Yuill-Braun five-category scores. preds/truths: [unit, day, family]."""
    counts = dict.fromkeys(CATEGORIES, 0)
    p = preds.reset_index(drop=True)
    consumed = set()
    for _, t in truths.sort_values(["unit", "day"], kind="stable").iterrows():
        cand = p[(p["unit"] == t["unit"])
                 & ((p["day"] - t["day"]).abs() <= match_days)
                 & (~p.index.isin(consumed))]
        if cand.empty:
            counts["missed"] += 1
            continue
        cand = cand.assign(_absd=(cand["day"] - t["day"]).abs())
        hit = cand.sort_values(["_absd", "day"], kind="stable").iloc[0]
        consumed.add(hit.name)
        fam = hit["family"]
        if fam == t["family"]:
            counts["correct"] += 1
        elif fam is None or fam == "no_response" or pd.isna(fam):
            counts["no_response"] += 1
        else:
            counts["misdiagnosis"] += 1
    counts["false_alarm"] = len(p) - len(consumed)
    return counts


def coolant_lack_lead_time(detections, events):
    """Baseline comparison #1: lead time of our detections vs the firmware
    CoolantLackLimit protection. STUB — lands at M4 with labeled data."""
    raise NotImplementedError("M4: requires labeled refrigerant events (O7 review queue)")


def title24_target_subcooling(detections, telemetry):
    """Baseline comparison #2: excess yield vs the Title-24 target-subcooling method.
    STUB — lands at M4 with labeled data."""
    raise NotImplementedError("M4: requires labeled refrigerant events (O7 review queue)")
