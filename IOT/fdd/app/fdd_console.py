# -*- coding: utf-8 -*-
"""FDD 本地控制台 — 零新增依赖的交互界面层。

设计约束(继承项目硬约束,本文件为纯工具层,不属管线):
- 全流程本地:仅 Python 标准库 + 项目既有依赖(pandas/numpy/CoolProp 经 fdd 模块间接
  使用);不安装任何第三方包、不调用任何外部 API、前端不加载任何 CDN 资源。
- 只读消费管线:只 import 并调用 src/fdd 既有模块,不修改任何管线行为与 tests/。
- 服务仅绑定 127.0.0.1(本机单用户工具)。
- 数据安全:界面只展示实验室机台编号(31/44/55/84/85),不触碰任何 SN/PII 数据源。
- 自检子进程继承会话铁规:环境中剔除 FDD_HMAC_KEY。

用法:
    .venv/Scripts/python app/fdd_console.py                 # 启动并自动打开浏览器
    .venv/Scripts/python app/fdd_console.py --no-browser --port 8765
或双击 fdd 根目录下 start_console.bat。
"""
import argparse
import base64
import datetime as dt
import functools
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = pathlib.Path(__file__).resolve().parent
ROOT = APP_DIR.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from fdd import baseline, c4, conv, diag, sense
from fdd.contracts.c1_telemetry import RAW_COLUMNS

LAB_DIR = ROOT / "data" / "raw" / "lab"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
STATIC_DIR = APP_DIR / "static"
MANUAL_MD = APP_DIR / "manual.md"
UPLOAD_DIR = pathlib.Path(tempfile.gettempdir()) / "fdd_console_uploads"
# 基线库工件:训练(读原始数据)与使用(检测/诊断)分离的落盘层。
# data/lake 在 gitignore 内 —— 工件是本机数据资产,不进代码仓库。
ARTIFACT_DIR = ROOT / "data" / "lake" / "console_baseline"

_LOCK = threading.Lock()
STATE = {
    "lab": None,
    "artifact": None,    # 当前基线库工件元数据(版本/溯源/指纹)
    "bins": None,        # 逐机×同箱健康基线缓存(装载后按需构建)
    "sense_ref": {},     # 逐机 sense 参照缓存(批量检测复用)
    "load": {"state": "idle", "error": None, "hint": None, "seconds": None},
    "selftest": {"state": "idle", "suite": None, "output": "", "summary": None,
                 "rc": None, "seconds": None},
    "batch": {"state": "idle", "total": 0, "done": 0, "current": None,
              "seconds": None, "error": None, "summary": None, "results": None},
}


class ApiError(Exception):
    """业务错误:error 给用户看,hint 告诉用户怎么办。"""

    def __init__(self, error: str, hint: str = ""):
        super().__init__(error)
        self.error, self.hint = error, hint


# ---------------------------------------------------------------- JSON 安全序列化

def _safe(o):
    if isinstance(o, dict):
        return {str(k): _safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_safe(x) for x in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if f != f else f
    if isinstance(o, float):
        return None if o != o else o
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, dt.datetime)):
        return o.isoformat(sep=" ")
    return o


def _round(v, n=3):
    try:
        f = float(v)
        return None if f != f else round(f, n)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 配置与健康

def api_config(_body=None):
    """阈值/工况点/频率带 → 前端提示与表单联动,永远与 calibration.yaml 同源。"""
    return {
        "diag": {
            "sh_norm_band_cool": diag.SH_NORM_BAND_COOL,
            "sh_high_cool": diag.SH_HIGH_COOL,
            "sc_low": diag.SC_LOW,
            "sc_high": diag.SC_HIGH,
            "cap_low": diag.CAP_LOW,
            "dsh_safety_min_k": diag.DSH_SAFETY_MIN_K,
            "heat_exv_up": diag.EXV_UP,
            "heat_sc_down": diag.SC_DOWN,
            "heat_cap_down": diag.CAP_DOWN,
            "heat_sh_high": diag.SH_HIGH,
        },
        "conditions": {"tolerance_c": c4.CONDITION_TOL,
                       "points": c4.CONDITION_POINTS},
        "capacity_band_hz": {"heat": list(c4.FULL_BAND_HZ["heat"]),
                             "cool": list(c4.FULL_BAND_HZ["cool"])},
        "lab_dir": str(LAB_DIR),
        "lab_dir_exists": LAB_DIR.exists(),
    }


KNOWN_STATE = [
    {"level": "info", "title": "M2 回归 3 项 skipped 属已知等待项,非异常",
     "detail": "holdout(留一 MAPE,等 M3 现场数据)、prodline×2(等 HMAC 盐协议;"
               "会话铁规剔除 FDD_HMAC_KEY 后恒 skip)。自检页预期值已按此标注。"},
    {"level": "warn", "title": "2436AA H2 健康锚仅 1 行(84 号机)",
     "detail": "envelope 的 H2 点为单行支撑,数据补充前脆弱(FDD-I-018 实测)。"},
    {"level": "warn", "title": "H4(−15℃)全负荷频率越 Full 带上界",
     "detail": "锚频 94–106 Hz > 带上界 86(2436AA 856/856 行、4860AA 89% 行越界);"
               "频率带不自扩,等人工调带(O-CERT/M3)。工况判定中 H4 容量档多为 "
               "UNKNOWN_CAPACITY 属预期现象。"},
    {"level": "info", "title": "u31×A 工况 197 行隔离标注(DK-016)",
     "detail": "试制机制冷 EEV 部分开度(Exv 286–316)判机台级异常:制冷侧参照池/标定"
               "统计排除,行保留作 exv 异常通道首个真实样本;机理待厂商(O-VENDOR)。"},
    {"level": "info", "title": "31 号机 5 个 2023-12-09 少冷媒文件 = 受控故障注入资产",
     "detail": "文件级 fault_injected 分流(FDD-I-017):行保留加载,锚/覆盖/包络全部"
               "健康基线消费者经同一分流排除。"},
    {"level": "info", "title": "NONSTD_HEAT(19.4℃ 制热)规则②在载入面休眠",
     "detail": "该温区段仅约 2.5 min,短于 surrogate 平台门 600 s,铸不成窗;"
               "envelope_input 语义由合成测试钉住,数据到货自动生效(FDD-I-018)。"},
    {"level": "warn", "title": "dsh 安全参考带 5.0 K 为暂定值",
     "detail": "dsh_safety_min_k=5.0 PROVISIONAL 待 Alan 定值(FDD-I-019-R1);当前"
               "仅触发核查清单注释行,绝不作诊断硬门。"},
    {"level": "info", "title": "控制器容量值(Qc/Qh)含 +2%~+12% 系统性偏差",
     "detail": "锁定发现:相对台架实测均值约 +7%;逐机漂移检测免疫,绝对容量陈述须带修正。"},
]


def api_health(_body=None):
    alerts = list(KNOWN_STATE)
    lab = STATE["lab"]
    dyn = []
    if lab is not None:
        healthy = lab[lab["data_type"] == "healthy_baseline"]
        cov = healthy[healthy["condition_class"] == "rating"].groupby(
            "sku")["test_condition"].nunique()
        for sku, n in cov.items():
            if n < 4:
                dyn.append({"level": "error",
                            "title": f"{sku} 健康额定工况覆盖不足({n}/4)",
                            "detail": "覆盖门要求每 SKU ≥4 个健康额定工况,当前数据不满足。"})
        q = lab.attrs.get("enum_quarantined", [])
        qtot = sum(sum(e["rows"].values()) for e in q)
        if qtot:
            comp = {}
            for e in q:
                for v, n in e["rows"].items():
                    comp[int(v)] = comp.get(int(v), 0) + int(n)
            beyond = {v: n for v, n in comp.items() if v not in (0, 1, 2, 3, 5, 10)}
            dyn.append({"level": "info",
                        "title": f"载入面枚举隔离 {qtot} 行(1s 面,不加载)",
                        "detail": f"构成 {dict(sorted(comp.items()))};其中表外未注册值 "
                                  f"{beyond or '无'}(已注册停机/过渡族 0/1/2/3/5/10 为预期)。"})
        um = lab.attrs.get("unmapped_units", {})
        if um:
            dyn.append({"level": "warn", "title": f"存在未映射机台 {sorted(um)}",
                        "detail": "config/unit_sku_map.yaml 未登记,文件被隔离未加载;"
                                  "补登记后重新装载即可纳入。"})
    return {"known": alerts, "dynamic": dyn, "loaded": lab is not None}


# ------------------------------------------------- 基线库工件(训练/使用分离)

def _config_fingerprint() -> dict:
    import hashlib
    out = {}
    for name in ("calibration.yaml", "unit_sku_map.yaml"):
        p = ROOT / "config" / name
        out[name] = hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None
    return out


def _artifact_versions():
    if not ARTIFACT_DIR.exists():
        return []
    out = []
    for mp in sorted(ARTIFACT_DIR.glob("v*.meta.json")):
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
            if (ARTIFACT_DIR / f"v{meta['version']}.pkl").exists():
                out.append(meta)
        except Exception:  # noqa: BLE001 — 损坏的元数据跳过
            continue
    return sorted(out, key=lambda m: m["version"])


def _save_artifact(lab: pd.DataFrame, load_seconds) -> dict:
    """把预处理后的 10s 载入面固化为版本化工件 + 溯源元数据。
    训练成本(解析上百个 1s CSV)只在这里发生一次;检测/诊断用工件秒级加载。"""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    versions = [m["version"] for m in _artifact_versions()]
    v = (max(versions) + 1) if versions else 1
    lab.to_pickle(ARTIFACT_DIR / f"v{v}.pkl")
    src = (lab.groupby(["unit", "source_file"]).size() if len(lab) else pd.Series(dtype=int))
    meta = {
        "version": v,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "schema": 1,
        "rows": int(len(lab)),
        "units": sorted(lab["unit"].dropna().unique().tolist()) if len(lab) else [],
        "source_files": int(src.shape[0]),
        "train_seconds": load_seconds,
        "lab_dir": str(LAB_DIR),
        "config_fingerprint": _config_fingerprint(),
        "attrs": {"duplicates_dropped": int(lab.attrs.get("duplicates_dropped", 0)),
                  "unmapped_units": lab.attrs.get("unmapped_units", {}),
                  "enum_quarantined_rows": int(sum(
                      sum(e["rows"].values())
                      for e in lab.attrs.get("enum_quarantined", [])))},
    }
    (ARTIFACT_DIR / f"v{v}.meta.json").write_text(
        json.dumps(_safe(meta), ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def _load_artifact(version=None):
    """加载工件(默认最新)→ 进入使用态;不触碰任何原始数据。"""
    versions = _artifact_versions()
    if not versions:
        return None
    meta = versions[-1] if version is None else next(
        (m for m in versions if m["version"] == version), None)
    if meta is None:
        raise ApiError(f"基线库版本 v{version} 不存在")
    lab = pd.read_pickle(ARTIFACT_DIR / f"v{meta['version']}.pkl")
    with _LOCK:
        STATE["lab"] = lab
        STATE["artifact"] = meta
        STATE["bins"] = None
        STATE["sense_ref"] = {}
        STATE["load"] = {"state": "done", "error": None, "hint": None,
                         "seconds": meta.get("train_seconds")}
    return meta


def api_artifact(_body=None):
    """基线库状态:当前工件、历史版本、配置指纹是否仍匹配、数据目录是否有新文件。"""
    cur = STATE["artifact"]
    now_fp = _config_fingerprint()
    stale = bool(cur and cur.get("config_fingerprint") != now_fp)
    data_newer, newest = False, None
    if cur and LAB_DIR.exists():
        try:
            mt = max((p.stat().st_mtime for p in LAB_DIR.rglob("*.csv")), default=None)
            if mt is not None:
                newest = dt.datetime.fromtimestamp(mt).isoformat(timespec="seconds")
                data_newer = newest > cur.get("created", "")
        except Exception:  # noqa: BLE001
            pass
    notes = []
    if stale:
        notes.append("配置文件(calibration/unit_sku_map)自本工件训练后已变更,"
                     "阈值类不受影响(实时读取),但基线构成可能过时——建议重新训练。")
    if data_newer:
        notes.append(f"数据目录中存在比当前工件更新的文件(最新 {newest})——"
                     "有新实验数据到货,建议重新训练以纳入基线。")
    return {"current": cur, "history": _artifact_versions(),
            "config_fingerprint_now": now_fp, "config_stale": stale,
            "data_newer": data_newer, "data_newest": newest,
            "loaded": STATE["lab"] is not None,
            "note": " / ".join(notes) if notes else None}


# ---------------------------------------------------------------- 数据装载与总览

def _do_load():
    t0 = time.time()
    try:
        lab = c4.load_lab(LAB_DIR)
        secs = round(time.time() - t0, 1)
        meta = _save_artifact(lab, secs)      # 训练完成即固化为新版工件
        with _LOCK:
            STATE["lab"] = lab
            STATE["artifact"] = meta
            STATE["bins"] = None      # 基线缓存随数据重建
            STATE["sense_ref"] = {}
            STATE["load"] = {"state": "done", "error": None, "hint": None,
                             "seconds": secs}
    except Exception as e:  # noqa: BLE001 — 前端需要完整失败原因
        with _LOCK:
            STATE["load"] = {"state": "error", "error": f"{type(e).__name__}: {e}",
                             "hint": "确认 data/raw/lab/ 下存在实验室数据(监控数据 目录);"
                                     "详细堆栈见控制台窗口。",
                             "seconds": round(time.time() - t0, 1)}
        traceback.print_exc()


def api_load(_body=None):
    with _LOCK:
        if STATE["load"]["state"] == "loading":
            return {"state": "loading"}
        if not LAB_DIR.exists():
            raise ApiError("实验室数据目录不存在:" + str(LAB_DIR),
                           "将实验室交付数据放到 data/raw/lab/ 后重试(O1 轨)。")
        STATE["load"] = {"state": "loading", "error": None, "hint": None, "seconds": None}
    threading.Thread(target=_do_load, daemon=True).start()
    return {"state": "loading"}


def api_load_status(_body=None):
    return dict(STATE["load"])


def _require_lab():
    lab = STATE["lab"]
    if lab is None:
        raise ApiError("基线库尚未就绪",
                       "到「① 基线与模型库」:已有工件会自动加载(秒级);首次使用请点击"
                       "「训练基线库」(读取原始实验数据,约 1 分钟,仅需一次)。")
    return lab


def api_overview(_body=None):
    lab = _require_lab()
    comp = (lab.groupby(["sku", "unit", "test_condition", "condition_class",
                         "data_type"], dropna=False)
            .agg(rows=("test_condition", "size"),
                 anchors=("rating_anchor", "sum"),
                 envelope_input=("envelope_input", "sum"))
            .reset_index())
    healthy = lab[lab["data_type"] == "healthy_baseline"]
    coverage = [{"sku": sku, "n": int(s.nunique()), "conditions": sorted(s.unique())}
                for sku, s in healthy[healthy["condition_class"] == "rating"]
                .groupby("sku")["test_condition"]]
    env = []
    for sku, g in lab[lab["envelope_input"].fillna(False).astype(bool)].groupby("sku"):
        try:
            model = baseline.fit_envelope(g, sku)
            for mode, ac in (("heating", 5), ("cooling", 4)):
                sub = g[g["AcState"] == ac]
                for cond in sorted(sub["test_condition"].unique()):
                    env.append({
                        "sku": sku, "mode": mode, "condition": cond,
                        "rows": int((sub["test_condition"] == cond).sum()),
                        "predicted_kw": _round(
                            baseline.predicted_capacity(model, mode, cond)),
                    })
                env.append({"sku": sku, "mode": mode, "condition": "— Ta 斜率 —",
                            "rows": int(len(sub)),
                            "predicted_kw": _round(
                                baseline.capacity_ta_slope(model, mode), 4)})
        except Exception as e:  # noqa: BLE001
            env.append({"sku": sku, "mode": "error", "condition": str(e),
                        "rows": 0, "predicted_kw": None})
    cards = {
        "rows": int(len(lab)),
        "units": sorted(lab["unit"].dropna().unique().tolist()),
        "skus": sorted(lab["sku"].dropna().unique().tolist()),
        "rating_anchor": int(lab["rating_anchor"].fillna(False).astype(bool).sum()),
        "envelope_input": int(lab["envelope_input"].fillna(False).astype(bool).sum()),
        "fault_injected": int((lab["data_type"] == "fault_injected").sum()),
        "quarantined": int(lab["cooling_ref_quarantine"].fillna(False).astype(bool).sum())
        if "cooling_ref_quarantine" in lab.columns else 0,
        "duplicates_dropped": int(lab.attrs.get("duplicates_dropped", 0)),
        "load_seconds": STATE["load"].get("seconds"),
    }
    return {"cards": cards, "coverage": coverage,
            "composition": comp.to_dict(orient="records"), "envelope": env}


def api_uncertainty(_body=None):
    lab = _require_lab()
    reports = []
    for (_u, _f), g in lab.groupby(["unit", "source_file"]):
        try:
            r = c4.uncertainty_report(g.sort_values("Timestamp"))
            if len(r):
                reports.append(r)
        except Exception:  # noqa: BLE001 — 单文件失败不阻塞整表
            continue
    if not reports:
        return {"rows": [], "note": "载入数据未产生任何不确定标记"
                                    "(AMBIGUOUS / UNKNOWN_CONDITION / UNSTABLE)。"}
    out = pd.concat(reports, ignore_index=True)
    return {"rows": out.to_dict(orient="records"), "note": f"共 {len(out)} 条标记。"}


# ---------------------------------------------------------------- 单点诊断

_RESID_KEYS = ("sh_resid", "sc_resid", "capacity_resid", "exv_resid",
               "lp_resid", "lp_abs_resid", "te_sat_resid")


def _fnum(body, key):
    v = body.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ApiError(f"字段 {key} 不是数字:{v!r}", "残差请输入数值,单位见字段旁提示。")


def _explain_cooling(row):
    sh = row.get("sh_resid", 0.0) or 0.0
    sc = row.get("sc_resid", 0.0) or 0.0
    cap = row.get("capacity_resid", 0.0) or 0.0
    e = [f"① SSH 先行(DK-015 次序):|sh_resid|={abs(sh):.2f}K,正常带 ±{diag.SH_NORM_BAND_COOL}K → "
         + ("正常带内" if abs(sh) <= diag.SH_NORM_BAND_COOL
            else ("高于带上界(> +" + str(diag.SH_HIGH_COOL) + "K)" if sh > diag.SH_HIGH_COOL
                  else "带外(负向,当前规则组不消费)")),
         f"② SC 判定:sc_resid={sc:.2f}K,低阈 {diag.SC_LOW}K / 高阈 +{diag.SC_HIGH}K → "
         + ("过冷度显著偏低(少冷媒方向)" if sc < diag.SC_LOW
            else ("过冷度显著偏高(节流受限方向)" if sc > diag.SC_HIGH else "正常区间")),
         f"③ 容量佐证(非硬门):capacity_resid={cap:.3f},佐证阈 {diag.CAP_LOW} → "
         + ("触发,并入证据并提升置信" if cap < diag.CAP_LOW else "未触发"),
         "铁律 17:制冷 EEV 满开非伺服,exv_resid 不作泄漏证据(仅指示 EEV 卡滞/控制异常);"
         "sh_resid 参照面 = 逐机×同箱(DK-017)。"]
    return e


def _explain_heating(row, exv_saturated):
    exv = row.get("exv_resid", 0.0) or 0.0
    sc = row.get("sc_resid", 0.0) or 0.0
    cap = row.get("capacity_resid", 0.0) or 0.0
    return [f"① EXV:exv_resid={exv:.1f},阈 ≥{diag.EXV_UP} → "
            + ("触发(泄漏三特征之一)" if exv >= diag.EXV_UP else "未触发"),
            f"② SC:sc_resid={sc:.2f}K,阈 ≤{diag.SC_DOWN} → "
            + ("触发" if sc <= diag.SC_DOWN else "未触发"),
            f"③ 容量:capacity_resid={cap:.3f},阈 ≤{diag.CAP_DOWN} → "
            + ("触发" if cap <= diag.CAP_DOWN else "未触发"),
            "铁律 3:制热 Sh 被 EEV 伺服钉在 ≈0,sh 证据仅在 exv_saturated=真 时启用"
            + f"(当前 {'已' if exv_saturated else '未'}饱和)。制热泄漏 = 三特征同时触发。"]


def api_diagnose(body):
    mode = body.get("mode")
    if mode not in ("cooling", "heating"):
        raise ApiError("mode 必须是 cooling 或 heating", "在表单顶部选择运行模式。")
    row = {}
    for k in _RESID_KEYS:
        v = _fnum(body, k)
        if v is not None:
            row[k] = v
    dshv = _fnum(body, "dsh_phys")
    if dshv is not None:
        row["dsh_phys"] = dshv
    exv_sat = bool(body.get("exv_saturated"))
    out = diag.diagnose(dict(row), mode=mode, exv_saturated=exv_sat)
    explain = (_explain_cooling(row) if mode == "cooling"
               else _explain_heating(row, exv_sat))
    notes = []
    if mode == "cooling" and row.get("exv_resid") and abs(row["exv_resid"]) >= 20 \
            and out["fault_hypothesis"] == "none":
        notes.append("exv_resid 单独大幅偏离:满开偏离 = EEV 卡滞/控制异常指示"
                     "(DK-009-d),该假设类不在 v0 输出,建议人工关注。")
    if dshv is not None and dshv < diag.DSH_SAFETY_MIN_K:
        notes.append(f"排气过热度 {dshv:.1f}K 低于安全参考带 {diag.DSH_SAFETY_MIN_K}K"
                     "(暂定值):已在核查清单追加压缩机安全行;此为注释,非诊断门。")
    if out.get("severity"):
        notes.append("severity 为未拟合方向性代理值(fitted=False),欠充梯度数据到货后"
                     "才有工程量纲,仅供相对参考。")
    return {"result": out, "explain": explain, "notes": notes}


# ---------------------------------------------------------------- 物理计算器

_CALC_FIELDS = ("Lp", "Hp", "Ts", "Tl", "Td", "Ta", "Tcs", "Th", "Tf", "CompRps",
                "FanRpm", "PowerIn", "PowerComp", "Comp", "Fan")


def api_materialize(body):
    mode = body.get("mode", "cooling")
    if mode not in ("cooling", "heating"):
        raise ApiError("mode 必须是 cooling 或 heating")
    vals = {}
    for k in _CALC_FIELDS:
        v = _fnum(body, k)
        if v is not None:
            vals[k] = v
    if not vals:
        raise ApiError("没有任何输入", "至少输入 Lp/Ts(过热度)或 Hp/Tl(过冷度)一组。")
    warnings = []
    for label, col in (("低压 Lp", "Lp"), ("高压 Hp", "Hp")):
        if col in vals:
            p_abs = vals[col] + 1.013
            if not (1.0 <= p_abs <= 46.0):
                warnings.append(f"{label}={vals[col]} bar(表压)→ 绝压 {p_abs:.2f} bar "
                                "超出饱和查表范围 [1,46],对应饱和温度不可信。")
    row = dict.fromkeys(RAW_COLUMNS, np.nan)
    row.update(vals)
    row["AcState"] = 4 if mode == "cooling" else 5
    row["St"] = 0 if mode == "cooling" else 1
    m = conv.materialize(pd.DataFrame([row])).iloc[0]
    derived = {k: _round(m.get(k)) for k in
               ("lp_abs", "hp_abs", "te_sat", "tc_sat", "sh_phys", "sc_phys",
                "dsh_phys", "tcs_gap")}
    hints = []
    if derived["sh_phys"] is not None and derived["sh_phys"] < 0:
        hints.append("过热度为负:Ts 低于蒸发饱和温度——检查 Lp/Ts 读数,或存在回液风险。")
    if derived["sc_phys"] is not None and derived["sc_phys"] < 0:
        hints.append("过冷度为负:Tl 高于冷凝饱和温度——检查 Hp/Tl 读数。")
    if derived["dsh_phys"] is not None and derived["dsh_phys"] < diag.DSH_SAFETY_MIN_K:
        hints.append(f"排气过热度 {derived['dsh_phys']}K < 安全参考带 "
                     f"{diag.DSH_SAFETY_MIN_K}K(暂定):压缩机回液/湿压缩风险,建议核查。")
    if mode == "heating":
        hints.append("提醒:制热模式 Sh≈0 是 EEV 伺服的正常状态(铁律 3);制热 Sc 含安装"
                     "管路温降偏置,只可逐机比较(铁律 10)。")
    cond = None
    if "Ta" in vals:
        letter, capa, confc = c4.condition_of(
            vals["Ta"], "cool" if mode == "cooling" else "heat", vals.get("CompRps"))
        cond = {"letter": letter or "UNKNOWN_CONDITION", "capacity": capa,
                "confidence": confc,
                "note": "容量档按 lab InvHz 全负荷带判定"
                        f"(制冷 {list(c4.FULL_BAND_HZ['cool'])} / 制热 "
                        f"{list(c4.FULL_BAND_HZ['heat'])} Hz,闭区间;现场 CompRps 另标定)。"}
    return {"derived": derived, "condition": cond, "warnings": warnings, "hints": hints}


# ---------------------------------------------------------------- 文件体检

@functools.lru_cache(maxsize=200000)
def _cond_cached(ta_r, mode, freq_r):
    return c4.condition_of(ta_r, mode, freq_r)


def _resolve_path(body) -> pathlib.Path:
    raw_path = (body.get("path") or "").strip().strip('"').strip("'")
    if not raw_path:
        raise ApiError("未选择文件", "用「浏览实验室数据」点选,或「从本机选取上传」;"
                                "高级用法才需要手动路径。")
    p = pathlib.Path(raw_path)
    if not p.exists():
        raise ApiError(f"文件不存在:{p}", "检查路径是否完整,含中文目录时确认无多余引号。")
    if p.suffix.lower() != ".csv":
        raise ApiError("仅支持 RamChecker 监控 CSV 文件")
    return p


def api_browse(body):
    """服务端目录树(限定 data/raw/lab 内,防目录穿越)。"""
    labroot = LAB_DIR.resolve()
    if not labroot.exists():
        raise ApiError("实验室数据目录不存在:" + str(labroot),
                       "任意位置的文件请改用「从本机选取上传」。")
    rel = (body.get("rel") or "").strip().replace("\\", "/")
    base = (labroot / rel).resolve() if rel else labroot
    if labroot != base and labroot not in base.parents:
        raise ApiError("目录越界", "浏览范围限定在 data/raw/lab 内;"
                                "其它位置请用「从本机选取上传」。")
    if not base.is_dir():
        raise ApiError("目录不存在:" + str(base))
    dirs, files = [], []
    for p in sorted(base.iterdir()):
        r = str(p.relative_to(labroot)).replace("\\", "/")
        if p.is_dir():
            n_csv = sum(1 for _ in p.rglob("*.csv"))
            dirs.append({"name": p.name, "rel": r, "path": str(p), "n_csv": n_csv})
        elif p.suffix.lower() == ".csv":
            files.append({"name": p.name, "rel": r, "path": str(p),
                          "size_kb": int(round(p.stat().st_size / 1024))})
    return {"root": str(labroot), "rel": rel, "dirs": dirs, "files": files}


def api_upload(body):
    """浏览器选取的文件 → base64 JSON → 本机临时目录(不进 data/ 仓库)。"""
    name = pathlib.Path(body.get("name") or "").name
    if not name.lower().endswith(".csv"):
        raise ApiError("仅支持 .csv 文件", "选择 RamChecker 监控 CSV。")
    try:
        raw = base64.b64decode(body.get("content_b64") or "", validate=True)
    except Exception:
        raise ApiError("上传内容解码失败", "重新选取文件;过大文件请改用手动路径方式。")
    if not raw:
        raise ApiError("上传内容为空")
    if len(raw) > 80 * 1024 * 1024:
        raise ApiError("文件超过 80MB 上限", "监控 CSV 通常仅数 MB,请确认选对了文件。")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / name
    dest.write_bytes(raw)
    return {"path": str(dest), "name": name,
            "size_kb": int(round(len(raw) / 1024)),
            "note": "已存入本机临时目录,仅本会话分析用,不进 data/ 仓库;"
                    "机台无法从路径推断,请在下拉框选择。"}


def api_manual(_body=None):
    if not MANUAL_MD.exists():
        raise ApiError("手册文件缺失:app/manual.md")
    return {"markdown": MANUAL_MD.read_text(encoding="utf-8")}


def _mask_sn(sn: str) -> str:
    """现场设备 SN 掩码(数据安全区:输出/共享物禁明文 SN;正式 HMAC 假名化属管线
    出域流程,控制台本地留档用 掩码+短哈希)。"""
    import hashlib
    sn = str(sn)
    h = hashlib.sha256(sn.encode()).hexdigest()[:8]
    if len(sn) <= 8:
        return f"***#{h}"
    return f"{sn[:4]}****{sn[-4:]}#{h}"


def _sniff_dialect(p: pathlib.Path) -> str:
    """lab = 实验室 RamChecker(ODU_CtrlMode/st1 方言);field = IoT 现场导出
    (AC_Data_RunState,C1 48 列或 48+扩展);prodline = 产线测试日志
    (ECOER_ProductionLine_Log,含 PCB/ODU 序列号与 Result 列);unknown = 都不是。"""
    head = open(p, encoding="utf-8", errors="replace").readline()
    if "PCB_SerialNo" in head or "ODU_SerialNo" in head or "LineMode" in head:
        return "prodline"
    if "ODU_CtrlMode" in head or "st1" in head:
        return "lab"
    if "AcState" in head and "Timestamp" in head and "CompRps" in head:
        return "field"
    return "unknown"


def _profile_prodline(p: pathlib.Path):
    """产线测试日志画像(C4 产线侧 / L2 出厂指纹轨道)。
    数据安全区:文件含明文 SN 两列(ODU/PCB)——统计后立即掩码并丢弃明文列,
    展示与导出永不出现明文;正式摄取(c4.load_prodline:C1 映射 + HMAC 假名化 +
    station/test_step)等 HMAC 盐协议(O-track)到位,控制台不代行、不自造盐。"""
    issues, info = [], {}
    df = pd.read_csv(p, encoding="utf-8", on_bad_lines="skip", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    devices, pcb_n = [], 0
    for col in ("ODU_SerialNo", "PCB_SerialNo"):
        if col in df.columns:
            vals = {v.strip() for v in df[col].dropna().astype(str)
                    if v.strip() and set(v.strip()) != {"-"}}
            if col == "ODU_SerialNo":
                devices = sorted(_mask_sn(v) for v in vals)
            else:
                pcb_n = len(vals)
            df = df.drop(columns=[col])          # 明文 SN 列立即丢弃
    num = df.apply(lambda s: pd.to_numeric(s, errors="coerce"))
    active = num["Hp"].notna() if "Hp" in num.columns else pd.Series(False, index=df.index)
    m = re.search(r"_(\d{14})", p.stem)
    day = (f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}" if m else "?")
    t = df["Time"].dropna().astype(str) if "Time" in df.columns else pd.Series(dtype=str)
    info.update({
        "dialect": "prodline", "unit": None, "data_type": "prodline",
        "rows_1s": int(len(df)), "rows_10s": None,
        "span": [f"{day} {t.iloc[0]}" if len(t) else "?",
                 f"{day} {t.iloc[-1]}" if len(t) else "?"],
        "active_rows": int(active.sum()),
        "devices_masked": devices, "pcb_count": pcb_n,
    })
    stats = {}
    for c in ("Hp", "Lp", "Ta", "Ts", "Td", "EEV", "INV"):
        if c in num.columns and num[c].notna().any():
            stats[c] = f"{_round(num[c].min(), 2)} ~ {_round(num[c].max(), 2)}"
    info["channel_ranges"] = stats
    for c, label in (("ResultOK", "result_ok"), ("ResultNG", "result_ng")):
        info[label] = int(num[c].fillna(0).sum()) if c in num.columns else None
    if "ErrCode" in num.columns:
        info["err_nonzero_rows"] = int((num["ErrCode"].fillna(0) != 0).sum())
    issues.append("产线测试日志(第三类数据源,L2 出厂指纹轨道):完整摄取需 c4.load_prodline"
                  "(C1 列映射 + 双 SN HMAC 假名化 + station/test_step),等 HMAC 盐协议"
                  "(O-track)到位——控制台只给画像,不做诊断、不代行假名化。"
                  "明文序列号已掩码,原始列已在内存中丢弃。")
    issues.append("产线数据为短程功能测试(非稳态运行),不适用运行诊断链;其价值 = 新设备"
                  "出厂基线(L2),待正式接入后供现场首检参照。")
    payload = {"info": info, "issues": issues, "conditions": [], "enum_quarantine": {}}
    return payload, None, None


def _read_field_csv(p: pathlib.Path) -> pd.DataFrame:
    """IoT 现场导出 → C1 形帧。现场格式即 C1 契约(48 列;新固件带扩展列,取 C1 子集,
    扩展列保留为 extras)。天然 10s 时基(铁律 6 无需重采样,只做间隙标记);压力已是
    bar、Qc/Qh 已是 kW、AcState/CompState 即 C1 枚举 —— 零换算。
    时区:样本为 -05:00,按悬而未决口径摄取并打 tz_unverified 标(去时区保留本地钟)。"""
    df = pd.read_csv(p, encoding="utf-8", on_bad_lines="skip")
    df.columns = [c.strip() for c in df.columns]
    if "Timestamp" not in df.columns:
        raise ApiError("现场文件缺 Timestamp 列", "确认是 AC_Data_RunState 导出。")
    ts = pd.to_datetime(df["Timestamp"], errors="coerce", utc=True)
    local = pd.to_datetime(df["Timestamp"].astype(str).str.slice(0, 19),
                           errors="coerce")          # 本地钟(去时区,tz_unverified)
    df["Timestamp"] = local
    df = df[df["Timestamp"].notna()].copy()
    for c in df.columns:
        if c not in ("Timestamp", "DayTime"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values("Timestamp").drop_duplicates(subset="Timestamp", keep="first")
    gap = df["Timestamp"].diff().dt.total_seconds()
    df["gap_flag"] = (gap > 15.0).fillna(False)
    _ = ts  # utc 解析仅用于校验可解析性
    return df.reset_index(drop=True)


def _field_device_of(p: pathlib.Path):
    """从文件名/目录取设备 SN(明文只留在本机路径;展示与导出一律掩码)。"""
    m = re.match(r"([A-Z]{2}\w+?)_AC_Data_RunState", p.name)
    if m:
        return m.group(1)
    m2 = re.match(r"([A-Z]{2}\w+?)_", p.parent.name)
    return m2.group(1) if m2 else None


def _profile_field(p: pathlib.Path):
    """现场文件体检:C1 直读 → 分段/稳态 → 逐行工况(容量档现场未标定,仅供参考)。"""
    issues, info = [], {}
    sn = _field_device_of(p)
    device = _mask_sn(sn) if sn else "未知设备"
    raw = _read_field_csv(p)
    info.update({"dialect": "field", "unit": device, "data_type": "field",
                 "rows_1s": None, "rows_10s": int(len(raw)),
                 "span": [str(raw["Timestamp"].min()), str(raw["Timestamp"].max())]})
    issues.append("现场数据口径注记:时区按样本 -05:00 摄取(tz_unverified);"
                  "容量档判定用实验室 InvHz 带,现场 CompRps 阈值未标定(M3),仅供参考;"
                  "固件上报 Sh/Sc 含饱和表偏差,本工具一律用物理口径重算。")
    if len(raw) < 30:
        issues.append("有效行不足 30,不可分析。")
        return ({"info": info, "issues": issues, "conditions": [],
                 "enum_quarantine": {}}, None, device)
    for c in RAW_COLUMNS:
        if c not in raw.columns:
            raw[c] = np.nan
    r = c4._with_anchor(raw)
    heat = r["AcState"].to_numpy() == 5
    letters = []
    for ta, h, hz in zip(np.round(r["Ta"].to_numpy(float), 2), heat,
                         np.round(r["CompRps"].to_numpy(float), 1)):
        letter, capa, _c = _cond_cached(float(ta), "heat" if h else "cool", float(hz))
        letters.append((letter or "UNKNOWN_CONDITION", capa))
    r["_letter"] = [x[0] for x in letters]
    r["_cap"] = [x[1] for x in letters]
    r["_device"] = device
    run_rows = int(r["AcState"].isin([4, 5]).sum())
    info.update({
        "ta": {"min": _round(r["Ta"].min()), "p50": _round(r["Ta"].median()),
               "max": _round(r["Ta"].max())},
        "mode_rows": {"cooling": int((r["AcState"] == 4).sum()),
                      "heating": int((r["AcState"] == 5).sum()),
                      "defrost": int((r["AcState"] == 7).sum())},
        "steady_rows": int(r["steady"].fillna(False).astype(bool).sum()),
        "anchor_clean": int((r["anchor_type"] == "clean_steady").sum()),
        "anchor_frost": int((r["anchor_type"] == "frosting_steady").sum()),
        "gap_rows": int(r["gap_flag"].fillna(False).astype(bool).sum()),
    })
    if run_rows == 0:
        issues.append("整段无制冷/制热运行行(停机/待机),无可诊断内容。")
    conds = (r[r["AcState"].isin([4, 5])].groupby(["_letter", "_cap"]).size()
             .reset_index(name="rows")
             .rename(columns={"_letter": "condition", "_cap": "capacity"})
             .sort_values("rows", ascending=False))
    if info["steady_rows"] == 0 and run_rows > 0:
        issues.append("无稳态行:全程瞬态/频繁调节,漂移筛查不可用。")
    payload = {"info": info, "issues": issues,
               "conditions": conds.to_dict(orient="records"),
               "enum_quarantine": {}}
    return payload, r, device


def _self_bins(frames) -> dict:
    """逐机自基线(现场模式):从同一设备本批数据的稳态行构建箱基线。
    参照面仍是逐机(铁律 10 的漂移比较面);局限:参照=数据自身,只能发现段间
    漂移/不一致,整程恒定的故障不可见 —— 输出必须带此标注。"""
    st = [f[f["steady"].fillna(False).astype(bool) & f["AcState"].isin([4, 5])]
          for f in frames]
    m = pd.concat(st, ignore_index=True) if st else pd.DataFrame()
    if not len(m):
        return {"bin": pd.DataFrame(columns=["unit", "AcState", "ta_bin", "rps_bin",
                                             "n", "sh", "sc", "exv", "q_kw"]),
                "letter": pd.DataFrame(columns=["unit", "AcState", "test_condition",
                                                "n", "sh", "sc", "exv", "q_kw"])}
    m = conv.materialize(m)
    m["ta_bin"] = (m["Ta"] // 2.0).astype(int)
    m["rps_bin"] = (m["CompRps"] // 10.0).astype(int)
    m["q_kw"] = np.where(m["AcState"] == 5, m["Qh"], m["Qc"])
    m["unit"] = m["_device"] if "_device" in m.columns else "self"
    g = (m.groupby(["unit", "AcState", "ta_bin", "rps_bin"])
         .agg(n=("sh_phys", "size"), sh=("sh_phys", "median"),
              sc=("sc_phys", "median"), exv=("Exv", "median"),
              q_kw=("q_kw", "median")).reset_index())
    g = g[g["n"] >= 12].reset_index(drop=True)
    m["test_condition"] = m["_letter"] if "_letter" in m.columns else "UNKNOWN_CONDITION"
    gl = (m.groupby(["unit", "AcState", "test_condition"])
          .agg(n=("sh_phys", "size"), sh=("sh_phys", "median"),
               sc=("sc_phys", "median"), exv=("Exv", "median"),
               q_kw=("q_kw", "median")).reset_index())
    gl = gl[gl["n"] >= 12].reset_index(drop=True)
    return {"bin": g, "letter": gl}


def _profile_file(p: pathlib.Path, unit_override=None):
    """体检共享管线:返回 (payload, 10s帧或None, unit)。payload 可直接作为体检结果。
    自动方言分派:实验室 RamChecker / IoT 现场导出。"""
    dialect = _sniff_dialect(p)
    if dialect == "field":
        return _profile_field(p)
    if dialect == "prodline":
        return _profile_prodline(p)
    issues, info = [], {}
    head = open(p, encoding="utf-8", errors="replace").readline()
    dialect_ok = ("st1" in head and "QrC_W" in head)
    if not dialect_ok:
        issues.append("63 列方言文件(表头缺 st1/QrC_W):核心字典未合并,载入面会整文件"
                      "跳过;仅能给出基础信息。")
    m = re.search(r"_(\d{14})", p.stem)
    if m is None:
        raise ApiError("文件名缺少 _YYYYMMDDHHMMSS 时间锚",
                       "RamChecker 原始命名含 14 位时间戳,时间轴重建依赖它;请勿改名。")
    anchor = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    raw = c4._read_monitor(p, anchor)
    info["rows_1s"] = int(len(raw))
    info["span"] = [str(raw["Timestamp"].min()), str(raw["Timestamp"].max())]
    unit = str(unit_override) if unit_override else c4._unit_of(p.parent.name)
    if unit:
        info["unit"] = unit
        try:
            from fdd import config as _fc
            info["data_type"] = _fc.data_type_of(unit, p.name)
        except Exception:  # noqa: BLE001
            info["data_type"] = None
        if info.get("data_type") == "fault_injected":
            issues.append("该文件登记为 fault_injected(受控故障注入资产):其行不入任何"
                          "健康基线/锚池,仅供诊断链与梯度标定。")
    else:
        info["unit"] = None
        info["data_type"] = None
    if not dialect_ok:
        return ({"info": info, "issues": issues, "conditions": [],
                 "enum_quarantine": {}}, None, unit)
    known = raw["ODU_CtrlMode"].isin(c4.ACSTATE_TRANSLATE)
    quarantine = {int(k): int(v) for k, v in
                  raw.loc[~known, "ODU_CtrlMode"].value_counts().items()}
    beyond = {v: n for v, n in quarantine.items() if v not in (0, 1, 2, 3, 5, 10)}
    if beyond:
        issues.append(f"发现表外未注册枚举值 {beyond}(行隔离不加载,铁律 15;"
                      "已注册停机/过渡族 0/1/2/3/5/10 为预期)。")
    raw = raw[known]
    if len(raw) < 30:
        issues.append("剔除停机/过渡后可用行不足 30(<30 秒),该文件在载入面不可用。")
        return ({"info": info, "issues": issues, "conditions": [],
                 "enum_quarantine": quarantine}, None, unit)
    d = c4._map_chunk(raw, p.name)
    r = c4._resample_10s(d)
    r = c4._with_anchor(r)
    heat = r["AcState"].to_numpy() == 5
    letters = []
    for ta, h, hz in zip(np.round(r["Ta"].to_numpy(float), 2), heat,
                         np.round(r["CompRps"].to_numpy(float), 1)):
        letter, capa, _c = _cond_cached(float(ta), "heat" if h else "cool", float(hz))
        letters.append((letter or "UNKNOWN_CONDITION", capa))
    r["_letter"] = [x[0] for x in letters]
    r["_cap"] = [x[1] for x in letters]
    info.update({
        "rows_10s": int(len(r)),
        "ta": {"min": _round(r["Ta"].min()), "p50": _round(r["Ta"].median()),
               "max": _round(r["Ta"].max())},
        "mode_rows": {"cooling": int((r["AcState"] == 4).sum()),
                      "heating": int((r["AcState"] == 5).sum()),
                      "defrost": int((r["AcState"] == 7).sum())},
        "steady_rows": int(r["steady"].fillna(False).astype(bool).sum()),
        "anchor_clean": int((r["anchor_type"] == "clean_steady").sum()),
        "anchor_frost": int((r["anchor_type"] == "frosting_steady").sum()),
        "gap_rows": int(r["gap_flag"].fillna(False).astype(bool).sum()),
    })
    conds = (r.groupby(["_letter", "_cap"]).size().reset_index(name="rows")
             .rename(columns={"_letter": "condition", "_cap": "capacity"})
             .sort_values("rows", ascending=False))
    if info["steady_rows"] == 0:
        issues.append("无稳态行:全程瞬态/频繁调节,该文件不产锚,只能用于瞬态分析。")
    payload = {"info": info, "issues": issues,
               "conditions": conds.to_dict(orient="records"),
               "enum_quarantine": quarantine}
    return payload, r, unit


def api_filecheck(body):
    p = _resolve_path(body)
    payload, _frame, _unit = _profile_file(p, body.get("unit") or None)
    return payload


# ------------------------------------------------------- 运行数据检测与诊断(detect)

def _baseline_bins() -> pd.DataFrame:
    """逐机×同箱健康基线:unit × AcState × Ta 2K 箱 × 频率 10Hz 档 的中位统计。
    数据面 = 已装载健康稳态行,排除 fault_injected 与 DK-016 隔离行;箱内 ≥12 行(2 分钟)。
    参照面依据:制冷 sh_resid = 逐机×同箱(DK-017);制热 Sc 禁跨机绝对比较(铁律 10)。"""
    lab = _require_lab()
    with _LOCK:
        if STATE.get("bins") is not None:
            return STATE["bins"]
    h = lab[(lab["data_type"] == "healthy_baseline")
            & lab["steady"].fillna(False).astype(bool)]
    if "cooling_ref_quarantine" in lab.columns:
        h = h[~h["cooling_ref_quarantine"].fillna(False).astype(bool)]
    m = conv.materialize(h)
    m = m[m["AcState"].isin([4, 5])]
    m["ta_bin"] = (m["Ta"] // 2.0).astype(int)
    m["rps_bin"] = (m["CompRps"] // 10.0).astype(int)
    m["q_kw"] = np.where(m["AcState"] == 5, m["Qh"], m["Qc"])
    g = (m.groupby(["unit", "AcState", "ta_bin", "rps_bin"])
         .agg(n=("sh_phys", "size"), sh=("sh_phys", "median"),
              sc=("sc_phys", "median"), exv=("Exv", "median"),
              q_kw=("q_kw", "median")).reset_index())
    g = g[g["n"] >= 12].reset_index(drop=True)
    # 第三级参照:逐机×同工况字母(窗面 test_condition;仍逐机,永不跨机)
    gl = (m.groupby(["unit", "AcState", "test_condition"])
          .agg(n=("sh_phys", "size"), sh=("sh_phys", "median"),
               sc=("sc_phys", "median"), exv=("Exv", "median"),
               q_kw=("q_kw", "median")).reset_index())
    gl = gl[gl["n"] >= 12].reset_index(drop=True)
    bins = {"bin": g, "letter": gl}
    with _LOCK:
        STATE["bins"] = bins
    return bins


# 行面字母 -> 窗面 test_condition 候选(FDD-I-016 后同名;同温歧义对枚举成员)
_LETTER_TO_WINDOW = {"A_or_A2": ["A", "A2"], "C_or_D": ["C", "D"]}


def _match_bin(bins, unit, ac, ta_bin, rps_bin, letter):
    """三级逐机参照:精确箱 → 同 Ta 箱跨频档 → 同工况字母。永不跨机(DK-017/铁律 10)。"""
    g = bins["bin"]
    ub = g[(g["unit"] == str(unit)) & (g["AcState"] == ac)]
    if len(ub):
        exact = ub[(ub["ta_bin"] == ta_bin) & (ub["rps_bin"] == rps_bin)]
        if len(exact):
            r = exact.iloc[0]
            return {"sh": r["sh"], "sc": r["sc"], "exv": r["exv"], "q_kw": r["q_kw"],
                    "n": int(r["n"]), "plane": "逐机×同箱(精确)"}, None
        ta_only = ub[ub["ta_bin"] == ta_bin]
        if len(ta_only):
            return {"sh": float(ta_only["sh"].median()),
                    "sc": float(ta_only["sc"].median()),
                    "exv": float(ta_only["exv"].median()),
                    "q_kw": float(ta_only["q_kw"].median()),
                    "n": int(ta_only["n"].sum()),
                    "plane": "逐机×同 Ta 箱(跨频率档参照,参考性下降)"}, None
    gl = bins["letter"]
    cands = _LETTER_TO_WINDOW.get(letter, [letter])
    ul = gl[(gl["unit"] == str(unit)) & (gl["AcState"] == ac)
            & gl["test_condition"].isin(cands)]
    if len(ul):
        return {"sh": float(ul["sh"].median()), "sc": float(ul["sc"].median()),
                "exv": float(ul["exv"].median()), "q_kw": float(ul["q_kw"].median()),
                "n": int(ul["n"].sum()),
                "plane": f"逐机×同工况 {letter}(跨 Ta/频率档参照,参考性下降)"}, None
    return None, (f"该机台在工况 {letter} 无任何健康基线"
                  "(逐机参照面,DK-017/铁律 10,不跨机凑基线)")


_HYP_RANK = {"refrigerant_low_or_leak": 3, "metering_restriction": 2,
             "indoor_side_nonspecific": 1, "none": 0}


def api_detect(body):
    p = _resolve_path(body)
    return _detect_file(p, body.get("unit") or None)


def _detect_file(p: pathlib.Path, unit_override=None, self_bins=None):
    """文件级检测与诊断核心(单文件与批量共用):
    体检 → 稳态分段 → 基线残差 → 逐段 M-DIAG → sense 信任检验。
    基线两种模式:lab(实验室机台,逐机三级参照)/ self(现场设备,逐机自基线漂移筛查)。"""
    payload, frame, unit = _profile_file(p, unit_override)
    is_field = payload["info"].get("dialect") == "field"
    out = {"profile": payload, "unit": unit, "baseline": None,
           "segments": [], "sensors": None, "sensor_note": None, "summary": None}
    if payload["info"].get("dialect") == "prodline":
        out["summary"] = {"verdict": "产线数据(仅画像)",
                          "detail": "产线测试日志属 L2 出厂指纹轨道:短程功能测试,不适用"
                                    "运行诊断链;完整摄取等 HMAC 盐协议后经 c4.load_prodline"
                                    "正式接入。画像见下。", "counts": {}}
        return out
    if frame is None:
        out["summary"] = {"verdict": "无法检测", "detail": "文件未通过体检(见问题项),"
                          "无法进入稳态分段与诊断。", "counts": {}}
        return out
    if is_field:
        # 现场设备:不在实验室基线池(逐机原则,禁止跨机)→ 逐机自基线漂移筛查。
        bins = self_bins if self_bins is not None else _self_bins([frame])
        in_pool = bool((bins["bin"]["unit"] == str(unit)).any())
        scope = "本批文件集" if self_bins is not None else "仅本文件"
        out["baseline"] = {
            "unit": unit, "in_pool": in_pool, "mode": "self",
            "artifact_version": None,
            "bins_for_unit": int((bins["bin"]["unit"] == str(unit)).sum()),
            "note": (f"【逐机自基线漂移筛查】参照 = 该设备自身稳态箱中位(范围:{scope})。"
                     "现场设备不进实验室基线(DK-017/铁律 10 禁止跨机);本模式只能发现"
                     "段间漂移/不一致,整程恒定的故障不可见;结论为方向性提示,"
                     "非 M3 验收诊断(现场健康基线随 M3 逐台积累后升级)。"
                     if in_pool else
                     "该设备稳态数据不足(<2 分钟稳态箱),自基线不可建 —— 仅提供画像;"
                     "多选同设备多个文件可扩大自基线样本。")}
    else:
        if STATE["lab"] is None:
            raise ApiError("基线库尚未就绪",
                           "到「① 基线与模型库」:已有工件自动加载;首次使用点「训练基线库」"
                           "——诊断残差以逐机健康基线为参照(快速体检不受影响)。")
        if not unit:
            raise ApiError("无法确定机台",
                           "上传文件没有目录上下文:请在「机台」下拉框选择后重试;"
                           "诊断基线是逐机的,机台错了结论就错了。")
        bins = _baseline_bins()
        in_pool = bool((bins["bin"]["unit"] == str(unit)).any())
        out["baseline"] = {
            "unit": unit, "in_pool": in_pool, "mode": "lab",
            "artifact_version": (STATE["artifact"] or {}).get("version"),
            "bins_for_unit": int((bins["bin"]["unit"] == str(unit)).sum()),
            "note": ("参照面 = 逐机三级:同箱(精确)→ 同 Ta 箱 → 同工况字母;"
                     "跨机/SKU 级参照禁止(DK-017/铁律 10)。"
                     if in_pool else
                     f"机台 {unit} 不在健康基线池中:无法出诊断结论,仅提供体检画像。"
                     "补充该机健康数据并重新装载后可诊断。")}
    for c in RAW_COLUMNS:            # 单文件帧补齐 C1 缺列(load_lab 在 concat 后才补)
        if c not in frame.columns:
            frame[c] = np.nan
    mm = conv.materialize(frame)
    st = mm["steady"].fillna(False).astype(bool)
    run_id = (st != st.shift()).cumsum()
    segments = []
    for _rid, g in mm[st].groupby(run_id[st]):
        if len(g) < 12:          # <2 分钟不成段
            continue
        ac_mode = g["AcState"].mode()
        ac = int(ac_mode.iat[0]) if len(ac_mode) else -1
        if ac not in (4, 5):
            continue
        mode = "heating" if ac == 5 else "cooling"
        med = {k: float(g[k].median()) for k in
               ("Ta", "CompRps", "Exv", "sh_phys", "sc_phys", "dsh_phys")}
        q_seg = float((g["Qh"] if ac == 5 else g["Qc"]).median())
        letter, cap, confc = c4.condition_of(
            med["Ta"], "heat" if ac == 5 else "cool", med["CompRps"])
        seg = {"t0": str(g["Timestamp"].iloc[0]), "t1": str(g["Timestamp"].iloc[-1]),
               "rows": int(len(g)), "dur_min": _round((len(g) * 10) / 60.0, 1),
               "mode": mode, "condition": letter or "UNKNOWN_CONDITION",
               "capacity_tag": cap, "ta": _round(med["Ta"], 2),
               "rps": _round(med["CompRps"], 1), "exv": _round(med["Exv"], 0),
               "sh_phys": _round(med["sh_phys"], 2), "sc_phys": _round(med["sc_phys"], 2),
               "dsh_phys": _round(med["dsh_phys"], 2), "q_kw": _round(q_seg, 2),
               "residuals": None, "baseline_bin": None, "diagnosis": None,
               "explain": None, "no_baseline_reason": None, "observations": []}
        base, why = _match_bin(bins, unit, ac, int(med["Ta"] // 2.0),
                               int(med["CompRps"] // 10.0),
                               letter or "UNKNOWN_CONDITION")
        if base is None:
            seg["no_baseline_reason"] = why
            segments.append(seg)
            continue
        res = {"sh_resid": med["sh_phys"] - base["sh"],
               "sc_resid": med["sc_phys"] - base["sc"],
               "exv_resid": med["Exv"] - base["exv"]}
        cap_res = ((q_seg - base["q_kw"]) / base["q_kw"]
                   if base["q_kw"] and base["q_kw"] == base["q_kw"]
                   and abs(base["q_kw"]) > 1e-6 else None)
        if cap_res is not None:
            res["capacity_resid"] = cap_res
        required = (("sh_resid", "sc_resid", "exv_resid", "capacity_resid")
                    if mode == "heating" else ("sh_resid", "sc_resid"))
        missing = [k for k in required
                   if res.get(k) is None or res.get(k) != res.get(k)]
        seg["baseline_bin"] = {k: _round(v, 3) if k != "plane" and k != "n" else v
                               for k, v in base.items()}
        seg["residuals"] = {k: _round(v, 3) for k, v in res.items()}
        if missing:
            seg["no_baseline_reason"] = ("主通道基线不完整(缺 " + "、".join(missing)
                                         + "),不出假设——宁缺勿错;可算通道见残差列。")
            for k, v in res.items():
                if v == v and v is not None:
                    seg["observations"].append(f"{k} = {v:+.3f}")
            segments.append(seg)
            continue
        row = {k: v for k, v in res.items() if v is not None and v == v}
        if med["dsh_phys"] == med["dsh_phys"]:
            row["dsh_phys"] = med["dsh_phys"]
        c5 = diag.diagnose(dict(row), mode=mode)
        seg["diagnosis"] = c5
        seg["explain"] = (_explain_cooling(row) if mode == "cooling"
                          else _explain_heating(row, False))
        segments.append(seg)
    out["segments"] = segments
    # ---- sense 传感器信任检验(逐机参照;失败不阻塞诊断主链;现场模式不做)
    if is_field:
        out["sensor_note"] = ("现场设备无实验室 sense 参照;自基线模式不做传感器信任检验"
                              "(避免用被检数据自证),随 M3 现场规格接入。")
        lab = None
    else:
        lab = STATE["lab"]
    try:
        if lab is None:
            raise RuntimeError("skip")
        hu = lab[(lab["unit"] == str(unit))
                 & (lab["data_type"] == "healthy_baseline")]
        if "cooling_ref_quarantine" in lab.columns:
            hu = hu[~hu["cooling_ref_quarantine"].fillna(False).astype(bool)]
        if len(hu) < 100:
            out["sensor_note"] = (f"机台 {unit} 健康行不足({len(hu)}<100),"
                                  "跳过传感器信任检验。")
        else:
            ref = STATE["sense_ref"].get(str(unit))
            if ref is None:
                ref = sense.fit_reference(conv.materialize(hu))
                with _LOCK:
                    STATE["sense_ref"][str(unit)] = ref
            chk = sense.check(mm, ref)
            out["sensors"] = chk.to_dict(orient="records")
            if (chk["status"] == "flagged").any():
                out["sensor_note"] = ("存在传感器信任旗:信任旗是仲裁输入而非独立判决;"
                                      "故障模式并发时故障解释优先(锁定发现)——按故障"
                                      "线索排查为主,传感器复核并行。另注:sense 阈值为"
                                      "临时标定(M4 用标签重标),存在偏敏可能。")
    except Exception as e:  # noqa: BLE001
        if not is_field:
            out["sensor_note"] = (f"传感器检验未完成({type(e).__name__}: {e}),"
                                  "不影响诊断结果。")
    # ---- 文件级汇总
    diagnosed = [s for s in segments if s["diagnosis"]]
    counts = {}
    for s in diagnosed:
        h = s["diagnosis"]["fault_hypothesis"]
        counts[h] = counts.get(h, 0) + 1
    undiagnosed = sum(1 for s in segments if s["no_baseline_reason"])
    worst = max(diagnosed, key=lambda s: (_HYP_RANK.get(
        s["diagnosis"]["fault_hypothesis"], 0), s["diagnosis"]["confidence"]),
        default=None)
    if not segments:
        verdict, detail = "无稳态段", "文件内没有 ≥2 分钟的稳态段,无法做段级诊断;可改用体检画像与瞬态观察。"
    elif not diagnosed:
        verdict, detail = "不可判(无逐机基线)", "所有稳态段都缺少该机台的健康基线;见各段标注。"
    elif worst and worst["diagnosis"]["fault_hypothesis"] != "none":
        h = worst["diagnosis"]["fault_hypothesis"]
        verdict = {"refrigerant_low_or_leak": "疑似少冷媒/泄漏",
                   "metering_restriction": "疑似节流受限",
                   "indoor_side_nonspecific": "内机侧非特异异常"}.get(h, h)
        detail = (f"最严重段:{worst['t0']} 起 {worst['dur_min']} 分钟,"
                  f"{worst['condition']} 工况,置信 {worst['diagnosis']['confidence']};"
                  f"共诊断 {len(diagnosed)} 段,{undiagnosed} 段无基线不可判。")
    else:
        verdict = "段间一致(自基线)" if is_field else "未见异常"
        detail = (f"共诊断 {len(diagnosed)} 段全部 none"
                  + (f";另有 {undiagnosed} 段无基线不可判。" if undiagnosed else "。"))
    if is_field and verdict not in ("无法检测", "无稳态段"):
        detail = "【逐机自基线漂移筛查,非 M3 验收诊断】" + detail
    out["summary"] = {"verdict": verdict, "detail": detail, "counts": counts,
                      "segments_total": len(segments),
                      "segments_diagnosed": len(diagnosed),
                      "segments_no_baseline": undiagnosed}
    return out


# ------------------------------------------------------- 批量检验(设备级汇总)

_ABNORMAL_VERDICTS = ("疑似少冷媒/泄漏", "疑似节流受限", "内机侧非特异异常")


def _collect_batch_paths(body):
    if body.get("paths"):
        paths = [pathlib.Path(str(x).strip().strip('"')) for x in body["paths"]]
        missing = [str(x) for x in paths if not x.exists()]
        if missing:
            raise ApiError("以下文件不存在:" + ";".join(missing[:3]),
                           "重新选取后再启动批量检验。")
        bad = [str(x) for x in paths if x.suffix.lower() != ".csv"]
        if bad:
            raise ApiError("仅支持 .csv 文件:" + bad[0])
        return paths
    d = (body.get("dir") or "").strip().strip('"').strip("'")
    if not d:
        raise ApiError("未选择目录或文件列表",
                       "在目录树点「选此目录批量」,或多选上传文件后再启动。")
    dp = pathlib.Path(d)
    if not dp.is_dir():
        raise ApiError(f"目录不存在:{dp}")
    paths = sorted(dp.rglob("*.csv"))
    if not paths:
        raise ApiError("目录内(含子目录)没有 .csv 文件")
    if len(paths) > 500:
        raise ApiError(f"目录内 CSV 达 {len(paths)} 个,超过 500 上限",
                       "选择更小的子目录分批检验。")
    return paths


def _batch_summary(results):
    units = {}
    for r in results:
        u = r["unit"] or "未知"
        e = units.setdefault(u, {"files": 0, "errors": 0, "abnormal": 0,
                                 "undiagnosable": 0, "counts": {}, "worst": None,
                                 "sensor_flagged_files": 0, "timeline": []})
        e["files"] += 1
        if r["error"]:
            e["errors"] += 1
            e["timeline"].append({"t": r["t_anchor"], "file": r["file"],
                                  "verdict": "错误", "conf": None})
            continue
        for k, v in (r["counts"] or {}).items():
            e["counts"][k] = e["counts"].get(k, 0) + v
        if r["verdict"] in _ABNORMAL_VERDICTS:
            e["abnormal"] += 1
            if (e["worst"] is None
                    or (r["worst_conf"] or 0) > (e["worst"].get("conf") or 0)):
                e["worst"] = {"file": r["file"], "verdict": r["verdict"],
                              "conf": r["worst_conf"], "t": r["t_anchor"]}
        if r["verdict"] and "不可判" in r["verdict"]:
            e["undiagnosable"] += 1
        if r["sensors_flagged"]:
            e["sensor_flagged_files"] += 1
        e["timeline"].append({"t": r["t_anchor"], "file": r["file"],
                              "verdict": r["verdict"], "conf": r["worst_conf"]})
    for e in units.values():
        e["timeline"].sort(key=lambda x: (x["t"] or ""))
    return {"files": len(results),
            "files_error": sum(1 for r in results if r["error"]),
            "files_abnormal": sum(1 for r in results
                                  if r["verdict"] in _ABNORMAL_VERDICTS),
            "files_undiagnosable": sum(1 for r in results
                                       if r["verdict"] and "不可判" in r["verdict"]),
            "files_clean": sum(1 for r in results
                               if r["verdict"] in ("未见异常", "段间一致(自基线)")),
            "units": units}


def _run_batch(paths, unit_override, is_field=False):
    t0 = time.time()
    results = []
    self_bins = None
    try:
        if is_field:
            # 现场批量:先跑一遍构建各设备的自基线(unit 列 = 掩码设备名),再逐文件筛查。
            with _LOCK:
                STATE["batch"]["current"] = "构建逐机自基线(第一遍扫描)…"
            frames = []
            for p in paths:
                try:
                    _pay, fr, _dev = _profile_file(p, unit_override)
                    if fr is not None:
                        frames.append(fr)
                except Exception:  # noqa: BLE001 — 坏文件第二遍会记录错误
                    continue
            self_bins = _self_bins(frames)
            del frames
        for i, p in enumerate(paths):
            with _LOCK:
                STATE["batch"]["done"] = i
                STATE["batch"]["current"] = p.name
            row = {"file": p.name, "path": str(p), "unit": None, "ok": False,
                   "verdict": None, "detail": None, "counts": {},
                   "seg_total": 0, "seg_diag": 0, "seg_nobase": 0,
                   "worst_conf": None, "sensors_flagged": [], "issues": 0,
                   "t_anchor": None, "error": None}
            m = re.search(r"_(\d{14})", p.stem)
            if m:
                s14 = m.group(1)
                row["t_anchor"] = (f"{s14[:4]}-{s14[4:6]}-{s14[6:8]} "
                                   f"{s14[8:10]}:{s14[10:12]}")
            else:                       # 现场导出:文件名含 ISO 起始时间
                mf = re.search(r"(\d{4}-\d{2}-\d{2})T(\d{2})_(\d{2})", p.stem)
                if mf:
                    row["t_anchor"] = f"{mf.group(1)} {mf.group(2)}:{mf.group(3)}"
            try:
                d = _detect_file(p, unit_override, self_bins=self_bins)
                sm = d.get("summary") or {}
                diagnosed = [s for s in d.get("segments", []) if s.get("diagnosis")]
                worst = max((s["diagnosis"]["confidence"] for s in diagnosed
                             if s["diagnosis"]["fault_hypothesis"] != "none"),
                            default=None)
                row.update({
                    "unit": d.get("unit"), "ok": True,
                    "verdict": sm.get("verdict"), "detail": sm.get("detail"),
                    "counts": sm.get("counts") or {},
                    "seg_total": sm.get("segments_total", 0),
                    "seg_diag": sm.get("segments_diagnosed", 0),
                    "seg_nobase": sm.get("segments_no_baseline", 0),
                    "worst_conf": worst,
                    "sensors_flagged": [x["sensor"] for x in (d.get("sensors") or [])
                                        if x.get("status") == "flagged"],
                    "issues": len((d.get("profile") or {}).get("issues") or []),
                })
            except ApiError as e:
                row["error"] = e.error
            except Exception as e:  # noqa: BLE001
                row["error"] = f"{type(e).__name__}: {e}"
            results.append(row)
        with _LOCK:
            STATE["batch"].update({"state": "done", "done": len(paths),
                                   "current": None,
                                   "seconds": round(time.time() - t0, 1),
                                   "summary": _batch_summary(results),
                                   "results": results})
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        with _LOCK:
            STATE["batch"].update({"state": "error",
                                   "error": f"{type(e).__name__}: {e}",
                                   "seconds": round(time.time() - t0, 1)})


def api_batch(body):
    with _LOCK:
        if STATE["batch"]["state"] == "running":
            raise ApiError("已有批量检验在运行", "等当前批次完成后再启动下一批。")
    paths = _collect_batch_paths(body)
    dialects = {_sniff_dialect(p) for p in paths}
    if "unknown" in dialects:
        bad = next(p for p in paths if _sniff_dialect(p) == "unknown")
        raise ApiError(f"存在无法识别格式的文件:{bad.name}",
                       "支持:实验室 RamChecker / IoT 现场 AC_Data_RunState / "
                       "产线 ProductionLine_Log 三种格式。")
    if len(dialects) > 1:
        raise ApiError("多种数据格式混批:" + " + ".join(sorted(dialects)),
                       "实验室(健康基线诊断)/ 现场(自基线漂移筛查)/ 产线(仅画像)"
                       "的分析模式不同,请分开批次运行。")
    kind = dialects.pop()
    is_field = kind == "field"
    if kind == "lab":
        if STATE["lab"] is None:
            raise ApiError("基线库尚未就绪",
                           "到「① 基线与模型库」加载或训练——实验室批量诊断的残差以"
                           "逐机健康基线为参照(现场/产线批量不需要)。")
        _baseline_bins()      # 预构建基线(在请求线程内,失败即时报错)
    unit_override = (body.get("unit") or "").strip() or None
    with _LOCK:
        STATE["batch"] = {"state": "running", "total": len(paths), "done": 0,
                          "current": None, "seconds": None, "error": None,
                          "summary": None, "results": None}
    threading.Thread(target=_run_batch, args=(paths, unit_override, is_field),
                     daemon=True).start()
    return {"state": "running", "total": len(paths), "mode": "field" if is_field else "lab"}


def api_batch_status(_body=None):
    return dict(STATE["batch"])


# ---------------------------------------------------------------- 系统自检

SUITES = {
    "m0": {"args": ["-m", "m0"], "label": "M0(conv/seg/zoho)",
           "expect": "13 passed"},
    "m1": {"args": ["-m", "m1"], "label": "M1(feat/drift/sense/label/valid/diag)",
           "expect": "53 passed"},
    "m2": {"args": ["-m", "m2"], "label": "M2(c4/baseline/envelope/SSD)",
           "expect": "55 passed + 3 skipped(3 项 skip 为已知等待项,非异常)"},
    "spec": {"args": ["tests/test_m2_condition_of.py", "tests/test_m2_envelope_input.py"],
             "label": "规格测试(condition_of + envelope_input)",
             "expect": "49 passed"},
}


def _run_selftest(suite):
    t0 = time.time()
    try:
        env = {k: v for k, v in os.environ.items() if k != "FDD_HMAC_KEY"}
        proc = subprocess.run(
            [str(VENV_PY), "-m", "pytest", *SUITES[suite]["args"], "-q"],
            cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=1200)
        lines = (proc.stdout + "\n" + proc.stderr).strip().splitlines()
        tail = "\n".join(lines[-30:])
        summary = next((l for l in reversed(lines)
                        if re.search(r"passed|failed|error|no tests ran", l)), "")
        with _LOCK:
            STATE["selftest"] = {"state": "done", "suite": suite, "output": tail,
                                 "summary": summary.strip(), "rc": proc.returncode,
                                 "seconds": round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            STATE["selftest"] = {"state": "error", "suite": suite,
                                 "output": f"{type(e).__name__}: {e}",
                                 "summary": None, "rc": -1,
                                 "seconds": round(time.time() - t0, 1)}


def api_selftest(body):
    suite = body.get("suite")
    if suite not in SUITES:
        raise ApiError(f"未知套件:{suite}", "可选:m0 / m1 / m2 / spec。")
    with _LOCK:
        if STATE["selftest"]["state"] == "running":
            raise ApiError("已有自检在运行", "等当前套件结束后再启动下一个。")
        if not VENV_PY.exists():
            raise ApiError("找不到项目虚拟环境 .venv/Scripts/python.exe",
                           "自检必须用项目 venv(Python 3.12),系统 Python 缺 fdd 包。")
        STATE["selftest"] = {"state": "running", "suite": suite, "output": "",
                             "summary": None, "rc": None, "seconds": None}
    threading.Thread(target=_run_selftest, args=(suite,), daemon=True).start()
    return {"state": "running", "suite": suite,
            "expect": SUITES[suite]["expect"], "label": SUITES[suite]["label"]}


def api_selftest_status(_body=None):
    st = dict(STATE["selftest"])
    if st.get("suite") in SUITES:
        st["expect"] = SUITES[st["suite"]]["expect"]
        st["label"] = SUITES[st["suite"]]["label"]
    return st


# ---------------------------------------------------------------- HTTP 层

ROUTES_GET = {
    "/api/config": api_config,
    "/api/health": api_health,
    "/api/load/status": api_load_status,
    "/api/overview": api_overview,
    "/api/selftest/status": api_selftest_status,
    "/api/batch/status": api_batch_status,
    "/api/artifact": api_artifact,
    "/api/manual": api_manual,
}
ROUTES_POST = {
    "/api/load": api_load,
    "/api/diagnose": api_diagnose,
    "/api/materialize": api_materialize,
    "/api/filecheck": api_filecheck,
    "/api/detect": api_detect,
    "/api/batch": api_batch,
    "/api/browse": api_browse,
    "/api/upload": api_upload,
    "/api/selftest": api_selftest,
    "/api/uncertainty": api_uncertainty,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "FDDConsole/1.0"

    def log_message(self, fmt, *args):  # 安静模式:只留错误
        if args and str(args[1] if len(args) > 1 else "").startswith("5"):
            sys.stderr.write("[http] " + (fmt % args) + "\n")

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(
            _safe(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _api(self, fn, body=None):
        try:
            self._send(200, {"ok": True, "data": fn(body)})
        except ApiError as e:
            self._send(200, {"ok": False, "error": e.error, "hint": e.hint})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._send(200, {"ok": False, "error": f"{type(e).__name__}: {e}",
                             "hint": "内部错误,完整堆栈见控制台窗口;可截图反馈。"})

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ROUTES_GET:
            return self._api(ROUTES_GET[path])
        if path in ("/", "/index.html"):
            page = STATIC_DIR / "index.html"
            if not page.exists():
                return self._send(500, {"ok": False,
                                        "error": "app/static/index.html 缺失"})
            return self._send(200, page.read_bytes(),
                              "text/html; charset=utf-8")
        return self._send(404, {"ok": False, "error": f"未知路径 {path}"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in ROUTES_POST:
            return self._send(404, {"ok": False, "error": f"未知路径 {path}"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except json.JSONDecodeError:
            return self._send(200, {"ok": False, "error": "请求体不是合法 JSON"})
        return self._api(ROUTES_POST[path], body)


def main():
    ap = argparse.ArgumentParser(description="FDD 本地控制台")
    ap.add_argument("--port", type=int, default=int(os.environ.get(
        "FDD_CONSOLE_PORT", "8765")))
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    try:                                  # 启动即用:自动加载最新基线库工件(秒级)
        meta = _load_artifact()
        if meta:
            print(f"[基线库] 已自动加载 v{meta['version']}"
                  f"(训练于 {meta['created']},{meta['rows']} 行)")
        else:
            print("[基线库] 尚无工件 —— 到「① 基线与模型库」页训练一次即可(约 1 分钟)")
    except Exception as e:  # noqa: BLE001 — 工件损坏不阻塞启动
        print(f"[基线库] 工件加载失败({type(e).__name__}: {e}),可在①页重新训练")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print("=" * 60)
    print("FDD 本地控制台已启动(仅本机可访问)")
    print(f"  地址: {url}")
    print("  停止: 关闭本窗口或 Ctrl+C")
    print("=" * 60)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
