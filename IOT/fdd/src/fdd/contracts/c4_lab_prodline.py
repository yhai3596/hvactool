"""C4 lab / production-line data contract: same structure as C1 plus tags.

First action on data arrival: run scripts/schema_diff.py; absorb any diff HERE, never in modules.
Factory fingerprint scope: component-level ONLY (sensors, compressor electrical, fan).
NEVER use factory data as a charge-state baseline (installation resets charge/piping).

TIMEBASE NORMALIZATION (contract clause, pinned 2026-07-03; implementation lands with M2
after the actual sampling rate is verified on delivered files):
- c4.load_lab / c4.load_prodline output is ALWAYS on the 10-second timebase (the fleet
  telemetry cadence every downstream window/point-count constant is anchored to).
- Sources sampled faster than 10 s (lab confirmed ~1 s, verify on arrival): resample per
  10-second window — numeric columns take the window MEDIAN, state columns (AcState /
  CompState / St, and any categorical) take the window MODE.
- BEFORE resampling: validate timestamp monotonicity and account for gaps; any window
  with a gap > 10 s gets gap_flag=True. Interpolation/fill of any kind is FORBIDDEN.
- Raw ~1 s source files stay untouched in data/raw/ (resampling is a load-time view,
  never a rewrite of the delivered artifact).
"""
LAB_EXTRA = ["test_condition"]        # AHRI point / extreme-condition type / transient tag
PRODLINE_EXTRA = ["station","test_step"]
