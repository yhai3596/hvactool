"""C4 contract layer — lab monitoring data mapping & 10 s timebase normalization (M2).

All format absorption lives HERE (contract layer); nothing leaks downstream.
Pinned items (Project instruction 2026-07-03 + adjudications):
- Timestamp rebuild: filename date anchor (RamChecker_YYYYMMDDHHMMSS) + midnight rollover
  (time-of-day diff < -12 h -> +1 day); duplicate timestamps keep-first, count in
  df.attrs["duplicates_dropped"].
- Pressures: source MPa x10 -> bar (C1 convention).
- Qc <- QrC_W/1000, Qh <- QrH_W/1000 (kW): recon appendix A verdict (identity
  Qch(kW) x1000 == active-mode QrX_W on 5/5 certified windows; InvQ eliminated).
- AcState enum normalization: ODU_CtrlMode 4->4(cooling), 11->5(heating), 13->7(defrost).
  Rows with any OTHER value are QUARANTINED (option A adjudication 2026-07-03): never
  translated, never loaded; counts registered in df.attrs["enum_quarantined"] and routed
  to the vendor question sheet (observed: 5 = cooling pre-stop seconds, 10 = startup
  transition, 0/1/2/3 = stop family; observation only, not a translation).
- CompState derivation (adjudicated 2026-07-03 with domain conditions: defrost only in
  heating context and ambient < 20 C; cooling keeps St==0 as its NORMAL position, St does
  not flip in cooling / warm ambient; mode transitions are infrequent so instantaneous
  AcState is a safe context):
      CompRps == 0                          -> 0
      AcState == 7                          -> 2
      St == 0 and AcState == 5 and Ta < 20  -> 2   (heating-context four-way flip)
      otherwise                             -> 1   (incl. cooling St==0 normal position)
  Provenance column compstate_derived=True.
- SKU mapping FINAL (数据说明.xlsx, Project-hardcoded 2026-07-03): units 37/84/31/55 ->
  EODA19H-2436AA, 44/85 -> EODA19H-4860AA; sku_provisional retired; `unit` column added.
- Dictionary of record: wade lab sheet (运行字段说明-wade补充v1.1.xlsx) adopted as the
  CROSS-GENERATION core dictionary — its 59 rows are the full set of one generation;
  62/63-col additions are merged into the rename map after per-generation recon.
  (Corrects the earlier phrasing \"59-col official mapping\"; ERRATA: the wade Tcs row
  carries a copy-paste error (duplicates another row's text); the Project-side premise
  \"units 84/85 are the 59-col generation\" was wrong — 84/85 are 62-col, the 20
  59-col files all live in unit 44. Both errata recorded here, mapping unaffected.)
- Qh/Qc <- QrX_W/1000 is now DOUBLE-EVIDENCED (bench discrimination appendix A + vendor
  dictionary): final. InvQ is annotated by the dictionary as compressor-side capacity —
  kept as an extra, never a Qh/Qc source.
- 10 s window resample: numeric median, state columns (AcState/CompState/St) window mode,
  windows containing a source gap > 10 s get gap_flag=True, interpolation FORBIDDEN.
- Mapping unit = certified bench-report window (time overlap); rows outside any certified
  window are UNMAPPED and never loaded (no guessing); 0-byte files quarantined.
- Two header generations (62-col with CompRps_FB/FanRpm_FB/SV1; 59-col without) share one
  rename table (the extra three columns are not mapped targets).
- C1 columns with no verified source stay NaN and are registered in NAN_FILLED.
"""
import datetime as dt
import pathlib
import re

import numpy as np
import pandas as pd

from fdd.contracts.c1_telemetry import RAW_COLUMNS

MONITOR_DIRNAME = "监控数据"

# verified rename map (recon II-2, physics-cross-checked); both header generations
RENAME = {
    "EV": "Exv", "InvHz": "CompRps", "st1": "St", "ODU_CtrlMode": "AcState",
    "Volt_1": "V1", "IA_2": "I2", "DC12": "V12", "DC15": "V15",
    "Y_Signal": "YSignal", "O_Signal": "OSignal", "PcW": "PowerComp",
    "Sh_Ts": "Sh", "Sc_TL": "Sc", "QrC_W": "Qc", "QrH_W": "Qh",
    # firmware saturation temps: ingested under _fw names, NEVER overwrite CoolProp cols
    "Teg": "teg_fw", "Tcg": "tcg_fw",
    # Ta/Ts/Tl/Th/Tf/Td/Lp/Hp/FanRpm/Tes/Tcs are same-name pass-through
}
# non-C1 columns ingested by decree (kept under original names as extras):
KEEP_EXTRA = ("HDSH", "Hsuc", "Hliq", "DltH", "Gr", "coil", "Error_Code")
UNIT_SKU = {  # 数据说明.xlsx — FINAL
    "37": "EODA19H-2436AA", "84": "EODA19H-2436AA", "31": "EODA19H-2436AA",
    "55": "EODA19H-2436AA", "44": "EODA19H-4860AA", "85": "EODA19H-4860AA",
}
ACSTATE_TRANSLATE = {4: 4, 11: 5, 13: 7}
STATE_COLS = ("AcState", "CompState", "St")
TAG_COLS = ("sku", "unit", "test_condition", "condition_class",
            "compstate_derived", "gap_flag", "source_file")
DEFROST_TA_MAX_C = 20.0     # adjudicated: no defrost / no heating above ~20 C ambient

NAN_FILLED = sorted(set(RAW_COLUMNS) - {"Timestamp"} - {
    "Ta", "Ts", "Tl", "Th", "Tf", "Td", "Lp", "Hp", "FanRpm", "Tes", "Tcs",
} - set(RENAME.values()) - {"CompState"})
# = DayTime, protection-limit columns, V2, Comp, Fan, N0, I1, PowerIn,
#   PowerCompTheo, Cch, WSignal, Dipsw — pending vendor dictionary; never invented.

# condition_class adjudication table: name prefix -> (class, basis). Longest prefix wins;
# anything unmatched is extreme. Basis strings are part of the mapping record (auditable).
CONDITION_CLASS = {
    "A":  ("rating", "AHRI A (35.0 C) cooling rating point"),
    "B":  ("rating", "AHRI B (27.8 C) cooling rating point"),
    "H1": ("rating", "AHRI H1 (8.3 C) heating rating point"),
    "H2": ("rating", "AHRI H2 (1.7 C) heating rating point"),
    "H3": ("rating", "AHRI H3 (-8.3 C) heating rating point"),
    "H4": ("rating", "AHRI 2023 M1 H4 (5 F / -15 C) low-temp heating point; 26 min "
                     "locked-frequency steady observed on bench; physics spot-check "
                     "passed (recon II-7); reclassified rating per Project 2026-07-03"),
}
EXTREME_BASIS = "non-rating bench program (defrost / oil return / other)"

# surrogate mapping for units WITHOUT bench certification windows (31/55), FDD-I-002 #5:
# nominal-zone + locked-frequency, gated by BOTH (Ta within nominal±3K) AND
# (capacity CV < 5% within the plateau); anything else stays UNMAPPED.
SURROGATE_UNITS = ("31", "55")
NOMINAL_TA = {"A": 35.0, "B": 27.8, "H1N": 8.3, "H2": 1.7, "H3": -8.3, "H4": -15.0}
SURROGATE_TA_TOL = 3.0
SURROGATE_CV_MAX = 0.05
SURROGATE_MIN_S = 600.0     # locked-frequency plateau >= 10 min


def _condition_class(name: str):
    for prefix in sorted(CONDITION_CLASS, key=len, reverse=True):
        if name.startswith(prefix):
            return CONDITION_CLASS[prefix]
    return ("extreme", EXTREME_BASIS)


def _reclassify(name: str, cls: str, basis: str, ta_med: float):
    """Evidence-driven rating re-adjudication (Project 2026-07-03): split/upgrade
    bench labels by MEASURED window ambient, never by label alone."""
    if name.startswith("H4"):
        if abs(ta_med + 15.0) <= 3.0:
            return "H4", "rating", CONDITION_CLASS["H4"][1]
        if abs(ta_med + 20.0) <= 3.0:
            return "H_low20", "extreme", (
                "measured Ta≈-20 C, below AHRI 2023 M1 H4 (5 F/-15 C); provisional name "
                "H_low20, official designation on the lab question list; split from "
                "metadata label 美标H4 by measured Ta")
        return name, "extreme", f"H4-labelled window at unexpected Ta={ta_med:.1f} C"
    if name == "自动除霜":
        if abs(ta_med - 1.7) <= 3.0:
            return "H2", "rating", (
                "AHRI H2 (1.7 C) frost-condition heating capacity point: window is pure "
                "heating (st1==1 throughout, reversal outside window; recon step-3), coil "
                "in frost zone, ambient matches H2 nominal; bench label was 自动除霜")
        return name, "extreme", EXTREME_BASIS + f" (measured Ta={ta_med:.1f} C)"
    return name, cls, basis


# ---------------------------------------------------------------- discovery

def _unit_of(folder_name: str):
    m = re.match(r"\s*(\d+)", folder_name)
    return m.group(1) if m else None


def _bench_windows(root: pathlib.Path) -> pd.DataFrame:
    """Certified condition windows from bench summary reports (Report_C metadata)."""
    rows = []
    for xlsx in sorted(root.rglob("*.xlsx")):
        if MONITOR_DIRNAME in xlsx.parts[-3:-1]:
            continue
        unit = _unit_of(xlsx.parent.name)
        if unit is None:
            continue
        try:
            raw = pd.read_excel(xlsx, sheet_name="Report_C", header=None)
        except Exception:
            continue
        cond = start = end = None
        for i in range(len(raw)):
            if raw.iat[i, 0] == "工况名称" and cond is None:
                cond = str(raw.iat[i, 6])
            if raw.iat[i, 0] == "报告开始时间" and start is None:
                start, end = raw.iat[i, 6], raw.iat[i, 17]
        if cond is None or start is None:
            continue
        name = cond.replace("美标", "").strip()
        cls, basis = _condition_class(name)
        rows.append({"unit": unit, "test_condition": name, "condition_class": cls,
                     "class_basis": basis, "t0": pd.Timestamp(start),
                     "t1": pd.Timestamp(end), "report_file": xlsx.name})
    return pd.DataFrame(rows)


def _monitor_csvs(root: pathlib.Path):
    mon = root / MONITOR_DIRNAME
    if not mon.exists():
        return []
    out = []
    for f in sorted(mon.rglob("*.csv")):
        if f.stat().st_size == 0:
            continue                    # quarantined empty files
        unit = _unit_of(f.parent.name)
        m = re.search(r"_(\d{14})", f.stem)
        if unit is None or m is None:
            continue                    # UNMAPPED file: isolated, never loaded
        out.append((unit, dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S"), f))
    return out


def _read_monitor(f: pathlib.Path, anchor: dt.datetime) -> pd.DataFrame:
    """Read one RamChecker CSV; rebuild full timestamps; coerce numerics."""
    df = pd.read_csv(f, encoding="utf-8", on_bad_lines="skip")
    t = pd.to_datetime(df["Time"], format="%H:%M:%S", errors="coerce")
    df = df[t.notna()].copy()
    t = t[t.notna()]
    sec = t.dt.hour * 3600 + t.dt.minute * 60 + t.dt.second
    day = (sec.diff() < -43200).cumsum().fillna(0)          # midnight rollover
    df["Timestamp"] = (pd.Timestamp(anchor.strftime("%Y-%m-%d"))
                       + pd.to_timedelta(day, unit="D") + pd.to_timedelta(sec, unit="s"))
    for c in df.columns:
        if c not in ("Time", "Timestamp"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.drop(columns=["Time"])


# ---------------------------------------------------------------- mapping

def _map_chunk(chunk: pd.DataFrame, source: str) -> pd.DataFrame:
    """Rename + unit conversions + enum translation + CompState derivation (1 s plane)."""
    d = chunk.rename(columns=RENAME).copy()
    d["Lp"] = d["Lp"] * 10.0                                # MPa -> bar
    d["Hp"] = d["Hp"] * 10.0
    d["Qc"] = d["Qc"] / 1000.0                              # W -> kW (C1 convention)
    d["Qh"] = d["Qh"] / 1000.0
    ac_raw = d["AcState"]
    unknown = sorted(set(ac_raw.dropna().astype(int)) - set(ACSTATE_TRANSLATE))
    if unknown:
        # rows are pre-filtered in load_lab (option A quarantine); reaching here is a bug
        raise AssertionError(f"unquarantined enum values {unknown} in {source}")
    d["AcState"] = ac_raw.map(ACSTATE_TRANSLATE)
    # official CompState semantics (vendor dict): 0=stop, 1=PI control, 2=special
    # (incl. STARTUP). Derivation below is defrost-focused and unchanged by decree;
    # startup rows land in 1 — accepted, provenance-flagged (compstate_derived).
    d["CompState"] = np.select(
        [d["CompRps"] == 0,
         (d["AcState"] == 7) | ((d["St"] == 0) & (d["AcState"] == 5)
                                & (d["Ta"] < DEFROST_TA_MAX_C))],
        [0, 2], default=1)
    return d


def _resample_10s(d: pd.DataFrame) -> pd.DataFrame:
    """10 s bins: numeric median, state mode, gap_flag on >10 s source gaps. No fill."""
    d = d.sort_values("Timestamp")
    n0 = len(d)
    d = d.drop_duplicates(subset="Timestamp", keep="first")
    dup = n0 - len(d)
    bins = d["Timestamp"].dt.floor("10s")
    gap = d["Timestamp"].diff().dt.total_seconds().groupby(bins.values).max()
    num_cols = [c for c in d.columns
                if c != "Timestamp" and pd.api.types.is_numeric_dtype(d[c])]
    g = d.groupby(bins.values)
    out = g[num_cols].median()
    for c in STATE_COLS:
        out[c] = g[c].agg(lambda s: s.mode().iat[0] if s.notna().any() else np.nan)
    out["gap_flag"] = (gap > 10.0).reindex(out.index).fillna(False).values
    out.index.name = "Timestamp"
    out = out.reset_index()
    out.attrs["duplicates_dropped"] = dup
    return out


def _surrogate_windows(raw: pd.DataFrame) -> list:
    """Locked-frequency plateaus qualifying as equivalent rating points (double gate).
    Returns [(condition, index_slice, ta_med, cv, dur_s), ...]; 63-col dialect files
    never reach here (caller filters on core-dictionary headers)."""
    out = []
    hz = raw["InvHz"]
    run = hz > 0
    plat = (hz != hz.shift()).cumsum()
    for _, p in raw[run].groupby(plat[run]):
        dur = (p["Timestamp"].iloc[-1] - p["Timestamp"].iloc[0]).total_seconds()
        if dur < SURROGATE_MIN_S:
            continue
        ta = float(p["Ta"].median())
        cond = next((c for c, nom in NOMINAL_TA.items()
                     if abs(ta - nom) <= SURROGATE_TA_TOL), None)
        if cond is None:
            continue
        heating = float(p["st1"].median()) == 1.0
        if heating and cond in ("A", "B"):
            continue                        # mode must match the nominal point
        if (not heating) and cond not in ("A", "B"):
            continue
        q = p["QrH_W"] if heating else p["QrC_W"]
        m = float(q.mean())
        if m <= 0:
            continue
        cv = float(q.std() / m)
        if cv >= SURROGATE_CV_MAX:
            continue
        out.append((cond, p.index, ta, cv, dur))
    return out


def load_lab(root) -> pd.DataFrame:
    """Load lab monitoring telemetry, C1-shaped, 10 s timebase, certified windows only.

    Rows outside every certified bench window are UNMAPPED -> never loaded (no label
    guessing). Raw 1 s files in data/raw stay untouched (this is a load-time view)."""
    root = pathlib.Path(root)
    windows = _bench_windows(root)
    chunks, dup_total, enum_quarantined = [], 0, []
    for unit, anchor, f in _monitor_csvs(root):
        wins = windows[windows["unit"] == unit]
        if not len(wins):
            if unit not in SURROGATE_UNITS:
                continue
            # surrogate route (FDD-I-002 #5): 62-col core-dictionary files only
            head = open(f, encoding="utf-8").readline()
            if "QrC_W" not in head or "st1" not in head:
                continue                    # 63-col dialect: unmapped until merged
            raw = _read_monitor(f, anchor)
            for cond, idx, ta_med, cv, dur in _surrogate_windows(raw):
                sel = raw.loc[idx]
                known = sel["ODU_CtrlMode"].isin(ACSTATE_TRANSLATE)
                if (~known).any():
                    q = sel.loc[~known, "ODU_CtrlMode"].value_counts().to_dict()
                    enum_quarantined.append({"file": f.name, "window": f"surrogate-{cond}",
                                             "unit": unit,
                                             "rows": {int(k): int(v) for k, v in q.items()}})
                    sel = sel[known]
                if len(sel) < 30:
                    continue
                d = _map_chunk(sel, f.name)
                r = _resample_10s(d)
                dup_total += r.attrs.get("duplicates_dropped", 0)
                r["sku"] = UNIT_SKU.get(unit, f"U{unit}")
                r["unit"] = unit
                r["test_condition"] = cond
                r["condition_class"] = "rating"
                r["source_file"] = f.name
                r["surrogate_ta"] = ta_med
                r["surrogate_cv"] = cv
                # FDD-I-003 #4: passed both physical gates but sits at the edge —
                # 55-B at Ta≈30.3 (2.5 K off nominal), 31-H2 at Ta≈0.55 (trial-production
                # unit x frosting condition, double uncertainty, lowest weight).
                # M3 re-validation should suspect the MAPPING first for these points.
                r["surrogate_edge"] = ((unit == "55" and cond == "B")
                                       or (unit == "31" and cond == "H2"))
                chunks.append(r)
            continue
        raw = None
        for _, w in wins.iterrows():
            # cheap prefilter on file anchor: skip files starting >1 day away
            if abs((anchor - w["t0"].to_pydatetime()).total_seconds()) > 86400 * 2:
                continue
            if raw is None:
                raw = _read_monitor(f, anchor)
            sel = raw[(raw["Timestamp"] >= w["t0"]) & (raw["Timestamp"] <= w["t1"])]
            # option A: quarantine rows whose ODU_CtrlMode is outside the verified enum
            known = sel["ODU_CtrlMode"].isin(ACSTATE_TRANSLATE)
            if (~known).any():
                q = sel.loc[~known, "ODU_CtrlMode"].value_counts().to_dict()
                enum_quarantined.append({"file": f.name, "window": w["test_condition"],
                                         "unit": unit, "rows": {int(k): int(v) for k, v in q.items()}})
                sel = sel[known]
            if len(sel) < 30:           # <30 s of usable overlap: not a usable window slice
                continue
            d = _map_chunk(sel, f.name)
            r = _resample_10s(d)
            dup_total += r.attrs.get("duplicates_dropped", 0)
            cond, cls, _basis = _reclassify(w["test_condition"], w["condition_class"],
                                            w["class_basis"], float(sel["Ta"].median()))
            r["sku"] = UNIT_SKU.get(unit, f"U{unit}")
            r["unit"] = unit
            r["test_condition"] = cond
            r["condition_class"] = cls
            r["source_file"] = f.name
            chunks.append(r)
    if not chunks:
        out = pd.DataFrame(columns=list(RAW_COLUMNS) + list(TAG_COLS))
    else:
        out = pd.concat(chunks, ignore_index=True)
    for c in NAN_FILLED:
        if c not in out.columns:
            out[c] = np.nan
    out["compstate_derived"] = True
    ordered = [c for c in RAW_COLUMNS if c in out.columns] + list(TAG_COLS)
    extras = [c for c in out.columns if c not in ordered]
    out = out[ordered + extras]
    out.attrs["duplicates_dropped"] = dup_total
    out.attrs["enum_quarantined"] = enum_quarantined
    return out


def schema_diff(df: pd.DataFrame) -> dict:
    missing = [c for c in RAW_COLUMNS if c not in df.columns]
    extra = [c for c in df.columns if c not in RAW_COLUMNS and c not in TAG_COLS]
    mismatch = []
    if "Timestamp" in df.columns and len(df) and not pd.api.types.is_datetime64_any_dtype(df["Timestamp"]):
        mismatch.append("Timestamp")
    return {"missing": missing, "extra": extra, "dtype_mismatch": mismatch}


# ---------------------------------------------------------------- annotations

_EVENT_RULES = [("报c2", "C2"), ("c2故障", "C2"), ("报c3", "C3"), ("c3", "C3"),
                ("复位", "复位"), ("断电", "断电"), ("除霜", "除霜")]

# curated events not carried by filenames (extraction provenance in raw_text)
CURATED_EVENTS = [
    {"unit": "84", "ts": dt.datetime(2024, 7, 1, 18, 2, 41), "event_type": "探头硬失效",
     "raw_text": "Th probe flyer +223C during defrost reversal "
                 "(RamChecker_20240701174201.csv); M-SENSE hard-failure POSITIVE sample "
                 "(FDD-I-002 #6 archival)"},
]


def load_lab_annotations(root) -> pd.DataFrame:
    """Event table from human-annotated monitoring filenames (unit 44 incident notes).
    Extraction only — no interpretation; raw_text keeps the full annotation."""
    root = pathlib.Path(root)
    rows = []
    mon = root / MONITOR_DIRNAME
    if mon.exists():
        for f in sorted(mon.rglob("*.csv")):
            m = re.match(r"RamChecker_(\d{14})\s+(.+)$", f.stem)
            if not m:
                continue
            text = m.group(2).strip()
            low = text.lower()
            etype = next((t for k, t in _EVENT_RULES if k in low), "其他")
            rows.append({"unit": _unit_of(f.parent.name),
                         "ts": dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S"),
                         "event_type": etype, "raw_text": text})
    rows.extend(CURATED_EVENTS)
    return pd.DataFrame(rows, columns=["unit", "ts", "event_type", "raw_text"])


# ---------------------------------------------------------------- periodic-program scan

# ---------------------------------------------------------------- prodline (draft)

# factory column dialect, recon-verified names only (docs/m2_factory_recon.md)
FACTORY_RENAME = {"TL": "Tl", "TL2": "Tl2", "EEV": "Exv", "Volt1": "V1",
                  "Current2": "I2", "ErrCode": "Error_Code"}


def pseudonymize_sn(raw_sn: str, key: str) -> str:
    """Pseudonymization protocol (CLAUDE.md data-security): normalize FIRST
    (strip / upper / remove spaces and hyphens), then HMAC-SHA256(key), hex[:16].
    Same rule for ODU and PCB serials and for all three data sources."""
    import hashlib
    import hmac as _hmac
    norm = str(raw_sn).strip().upper().replace(" ", "").replace("-", "")
    return _hmac.new(key.encode(), norm.encode(), hashlib.sha256).hexdigest()[:16]


def load_prodline(root) -> pd.DataFrame:
    """DRAFT (recon stage). Pinned: St = 1 - factory '4-way-valve' (polarity to be
    confirmed on full data: heating segments must yield St==1 after inversion);
    TL case-normalized via FACTORY_RENAME; ODU_SerialNo -> hash_sn and
    PCB_SerialNo -> hash_pcb_sn via pseudonymize_sn; cleartext SN never crosses
    this boundary. REFUSES to run without FDD_HMAC_KEY — before reading anything."""
    import os
    if not os.environ.get("FDD_HMAC_KEY"):
        raise RuntimeError("FDD_HMAC_KEY UNSET — load_prodline refuses "
                           "(pseudonymization protocol, CLAUDE.md)")
    raise NotImplementedError("factory mapping lands after full factory recon adjudication")


def periodic_program_scan(root) -> pd.DataFrame:
    """Mandatory companion of the CompState derivation: hunt the fleet's periodic
    low-frequency program signature in lab heating runs. Signature (pinned):
    frequency plateau <= 0.7 x median frequency of the preceding 10 min, lasting
    3-15 min, St constant 1, Exv narrowed vs the preceding 10 min. Detection only —
    zero handling; any hit is reported upstream and stops the derivation rollout."""
    root = pathlib.Path(root)
    hits = []
    for unit, anchor, f in _monitor_csvs(root):
        raw = _read_monitor(f, anchor)
        need = {"ODU_CtrlMode", "InvHz", "st1", "EV", "Ta"}
        if not need <= set(raw.columns):
            continue
        heat = (raw["ODU_CtrlMode"] == 11) & (raw["InvHz"] > 0)
        seg_id = (heat != heat.shift()).cumsum()
        for _, g in raw[heat].groupby(seg_id[heat]):
            g = g.sort_values("Timestamp")
            plat_id = (g["InvHz"] != g["InvHz"].shift()).cumsum()
            for _, p in g.groupby(plat_id):
                dur = (p["Timestamp"].iloc[-1] - p["Timestamp"].iloc[0]).total_seconds()
                if not (180.0 <= dur <= 900.0):
                    continue
                pre = g[(g["Timestamp"] < p["Timestamp"].iloc[0])
                        & (g["Timestamp"] >= p["Timestamp"].iloc[0] - pd.Timedelta(minutes=10))]
                if len(pre) < 60:
                    continue
                prev_hz = float(pre["InvHz"].median())
                if prev_hz <= 0 or float(p["InvHz"].iloc[0]) > 0.7 * prev_hz:
                    continue
                if not (p["st1"] == 1).all():
                    continue
                if not float(p["EV"].median()) < float(pre["EV"].median()):
                    continue
                hits.append({"unit": unit, "file": f.name,
                             "t_start": p["Timestamp"].iloc[0], "t_end": p["Timestamp"].iloc[-1],
                             "dur_s": dur, "plateau_hz": float(p["InvHz"].iloc[0]),
                             "prev10min_hz_med": prev_hz,
                             "exv_med": float(p["EV"].median()),
                             "exv_prev_med": float(pre["EV"].median())})
    return pd.DataFrame(hits, columns=["unit", "file", "t_start", "t_end", "dur_s",
                                       "plateau_hz", "prev10min_hz_med", "exv_med",
                                       "exv_prev_med"])
