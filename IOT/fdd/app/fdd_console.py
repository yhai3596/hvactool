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
import datetime as dt
import functools
import json
import os
import pathlib
import re
import subprocess
import sys
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

from fdd import baseline, c4, conv, diag
from fdd.contracts.c1_telemetry import RAW_COLUMNS

LAB_DIR = ROOT / "data" / "raw" / "lab"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
STATIC_DIR = APP_DIR / "static"

_LOCK = threading.Lock()
STATE = {
    "lab": None,
    "load": {"state": "idle", "error": None, "hint": None, "seconds": None},
    "selftest": {"state": "idle", "suite": None, "output": "", "summary": None,
                 "rc": None, "seconds": None},
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


# ---------------------------------------------------------------- 数据装载与总览

def _do_load():
    t0 = time.time()
    try:
        lab = c4.load_lab(LAB_DIR)
        with _LOCK:
            STATE["lab"] = lab
            STATE["load"] = {"state": "done", "error": None, "hint": None,
                             "seconds": round(time.time() - t0, 1)}
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
        raise ApiError("数据尚未装载", "先在「数据总览」页点击「装载实验室数据」(约 40–60 秒)。")
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


def api_filecheck(body):
    raw_path = (body.get("path") or "").strip().strip('"').strip("'")
    if not raw_path:
        raise ApiError("路径为空", "粘贴 RamChecker CSV 的完整路径(可在资源管理器中"
                                "右键文件 → 复制文件地址)。")
    p = pathlib.Path(raw_path)
    if not p.exists():
        raise ApiError(f"文件不存在:{p}", "检查路径是否完整,含中文目录时确认无多余引号。")
    if p.suffix.lower() != ".csv":
        raise ApiError("仅支持 RamChecker 监控 CSV 文件")
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
    if not dialect_ok:
        return {"info": info, "issues": issues, "conditions": [], "enum_quarantine": {}}
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
        return {"info": info, "issues": issues, "conditions": [],
                "enum_quarantine": quarantine}
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
    unit = c4._unit_of(p.parent.name)
    if unit:
        dtye = None
        try:
            from fdd import config as _fc
            dtye = _fc.data_type_of(unit, p.name)
        except Exception:  # noqa: BLE001
            pass
        info["unit"] = unit
        info["data_type"] = dtye
        if dtye == "fault_injected":
            issues.append("该文件登记为 fault_injected(受控故障注入资产):其行不入任何"
                          "健康基线/锚池,仅供诊断链与梯度标定。")
    return {"info": info, "issues": issues,
            "conditions": conds.to_dict(orient="records"),
            "enum_quarantine": quarantine}


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
}
ROUTES_POST = {
    "/api/load": api_load,
    "/api/diagnose": api_diagnose,
    "/api/materialize": api_materialize,
    "/api/filecheck": api_filecheck,
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
