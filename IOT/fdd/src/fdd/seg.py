"""M-SEG state segmentation & steady-state detector. Milestone: M0.

Hard rules #6 #7 bind here.
DoD (tests/test_m0_seg.py) on data/sample:
  - exactly 2 defrost segments (St-based) and 5 special segments detected
  - zero steady rows inside CompState==2
  - steady coverage in [0.40, 0.80] of run rows
"""
import pandas as pd

STEADY_MIN_MINUTES = 5.0
ROLL_WINDOW_MIN = 2.0
# thresholds calibrated on sample; re-calibrate when lab transient data arrives (M2)
RPS_STD_MAX = 1.5
EXV_STD_MAX = 6.0

def segment(df: pd.DataFrame) -> pd.DataFrame:
    """Add columns: segment_id, segment_type in
    {run, off, defrost, special, transition}, steady(bool).
    defrost := CompState==2 AND St flipped to 0 within segment (Th spike = verification only).
    special := CompState==2 AND St stays 1 (periodic low-freq program -> ALWAYS excluded).
    steady  := run AND >STEADY_MIN_MINUTES into segment AND rolling std(CompRps)<RPS_STD_MAX
               AND rolling std(Exv)<EXV_STD_MAX."""
    raise NotImplementedError

def summarize_segments(df: pd.DataFrame) -> pd.DataFrame:
    """Per-segment summary: type, duration, key means (for QA reports)."""
    raise NotImplementedError
