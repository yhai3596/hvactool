"""C4 lab / production-line data contract: same structure as C1 plus tags.

First action on data arrival: run scripts/schema_diff.py; absorb any diff HERE, never in modules.
Factory fingerprint scope: component-level ONLY (sensors, compressor electrical, fan).
NEVER use factory data as a charge-state baseline (installation resets charge/piping).
"""
LAB_EXTRA = ["test_condition"]        # AHRI point / extreme-condition type / transient tag
PRODLINE_EXTRA = ["station","test_step"]
