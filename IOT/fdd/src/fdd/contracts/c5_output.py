"""C5 diagnostic output: the five-piece evidence pack. Only aggregates/models ever leave the domain."""
OUTPUT_SCHEMA = ["hash_sn","window_start","window_end","fault_hypothesis",
                 "evidence","counter_evidence","confidence","field_checklist","version"]
# evidence / counter_evidence: list[{feature, direction, magnitude}]
