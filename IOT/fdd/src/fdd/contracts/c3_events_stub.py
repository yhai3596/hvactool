"""C3 platform fault-event contract (STUB - real schema pending, see plan v1.1 appendix B).

Field-mapping layer isolates the real schema; the join engine codes against THIS.
Join window: platform event ts in [ticket_event_date - 21d, +3d].
"""
EVENT_SCHEMA = ["hash_sn","ts_utc","fault_code","code_meaning","protection_bit","severity",
                "cleared_ts","model","telemetry_first_date","telemetry_last_date","fw_version"]
JOIN_WINDOW_DAYS = (-21, +3)
