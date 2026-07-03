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
- SKU provisional: unit-number placeholders ("U44"...), sku_provisional=True until the
  O-track series->SKU answer replaces them.
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
    # Ta/Ts/Tl/Th/Tf/Td/Lp/Hp/FanRpm/Tes/Tcs are same-name pass-through
}
ACSTATE_TRANSLATE = {4: 4, 11: 5, 13: 7}
STATE_COLS = ("AcState", "CompState", "St")
TAG_COLS = ("sku", "test_condition", "condition_class", "sku_provisional",
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


def _condition_class(name: str):
    for prefix in sorted(CONDITION_CLASS, key=len, reverse=True):
        if name.startswith(prefix):
            return CONDITION_CLASS[prefix]
    return ("extreme", EXTREME_BASIS)


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
            r["sku"] = f"U{unit}"
            r["test_condition"] = w["test_condition"]
            r["condition_class"] = w["condition_class"]
            r["source_file"] = f.name
            chunks.append(r)
    if not chunks:
        out = pd.DataFrame(columns=list(RAW_COLUMNS) + list(TAG_COLS))
    else:
        out = pd.concat(chunks, ignore_index=True)
    for c in NAN_FILLED:
        if c not in out.columns:
            out[c] = np.nan
    out["sku_provisional"] = True
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
    return pd.DataFrame(rows, columns=["unit", "ts", "event_type", "raw_text"])


# ---------------------------------------------------------------- periodic-program scan

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
