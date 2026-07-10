#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HVAC 工具站本地服务
  - 静态文件托管（本目录）
  - CoolProp 物性 API（冷媒 / 湿空气 / 水与乙二醇溶液）
运行:  python server.py   →  http://127.0.0.1:8137
依赖:  pip install coolprop
"""
import json
import math
import os
import time
import traceback
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from CoolProp.CoolProp import PropsSI, HAPropsSI

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8137

# 展示名 → CoolProp 名
FLUIDS = {
    'R410A': 'R410A', 'R32': 'R32', 'R454B': 'R454B.mix',
    'R134a': 'R134a', 'R290': 'R290', 'R404A': 'R404A',
    'R407C': 'R407C', 'R22': 'R22', 'R1234yf': 'R1234yf',
    'R600a': 'R600a', 'R717': 'R717', 'R744': 'R744',
}
GLIDE_BLENDS = {'R454B', 'R407C', 'R404A', 'R410A'}   # 非共沸/近共沸，报告滑移

# 预定义混合物无法用 Props1SI 查临界参数 → 文献常数兜底
# R454B (Opteon XL41): Tc 78.1°C, Pc 5.267 MPa, M 62.6 g/mol
_CRIT_FALLBACK = {'R454B.mix': {'T': 351.25, 'P': 5267e3, 'M': 0.0626}}
_CRIT_CACHE = {}


def crit(cn):
    if cn not in _CRIT_CACHE:
        if cn in _CRIT_FALLBACK:
            _CRIT_CACHE[cn] = _CRIT_FALLBACK[cn]
        else:
            _CRIT_CACHE[cn] = {
                'T': PropsSI('TCRIT', cn),
                'P': PropsSI('PCRIT', cn),
                'M': PropsSI('MOLARMASS', cn),
            }
    return _CRIT_CACHE[cn]


# 焓熵基准统一为 IIR（0°C 饱和液 h=200 kJ/kg, s=1.0 kJ/kg·K），与常用表册一致
_OFFSETS = {}


def offsets(cp_name):
    if cp_name not in _OFFSETS:
        try:
            h0 = PropsSI('H', 'T', 273.15, 'Q', 0, cp_name)
            s0 = PropsSI('S', 'T', 273.15, 'Q', 0, cp_name)
            _OFFSETS[cp_name] = (h0 - 200000.0, s0 - 1000.0)
        except Exception:
            _OFFSETS[cp_name] = (0.0, 0.0)
    return _OFFSETS[cp_name]


def disp_h(cp_name, h_si):
    return (h_si - offsets(cp_name)[0]) / 1000.0


def disp_s(cp_name, s_si):
    return (s_si - offsets(cp_name)[1]) / 1000.0


def si_h(cp_name, h_kjkg):
    return h_kjkg * 1000.0 + offsets(cp_name)[0]


def si_s(cp_name, s_kj):
    return s_kj * 1000.0 + offsets(cp_name)[1]


def cp_fluid(name):
    if name not in FLUIDS:
        raise ValueError('未知冷媒: %s' % name)
    return FLUIDS[name]


def maybe(fn):
    try:
        v = fn()
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return None
        return v
    except Exception:
        return None


def sat_info(cp_name, P=None, T=None):
    """P(Pa) 或 T(K) 处的饱和信息（含滑移）"""
    out = {}
    if P is not None:
        Tb = maybe(lambda: PropsSI('T', 'P', P, 'Q', 0, cp_name))
        Td = maybe(lambda: PropsSI('T', 'P', P, 'Q', 1, cp_name))
        if Tb is None or Td is None:
            return None
        out['t_bubble'] = Tb - 273.15
        out['t_dew'] = Td - 273.15
        out['glide'] = Td - Tb
        out['hf'] = disp_h(cp_name, PropsSI('H', 'P', P, 'Q', 0, cp_name))
        out['hg'] = disp_h(cp_name, PropsSI('H', 'P', P, 'Q', 1, cp_name))
        out['sf'] = disp_s(cp_name, PropsSI('S', 'P', P, 'Q', 0, cp_name))
        out['sg'] = disp_s(cp_name, PropsSI('S', 'P', P, 'Q', 1, cp_name))
        out['rhof'] = PropsSI('D', 'P', P, 'Q', 0, cp_name)
        out['rhog'] = PropsSI('D', 'P', P, 'Q', 1, cp_name)
        out['latent'] = out['hg'] - out['hf']
    else:
        Pb = maybe(lambda: PropsSI('P', 'T', T, 'Q', 0, cp_name))
        Pd = maybe(lambda: PropsSI('P', 'T', T, 'Q', 1, cp_name))
        if Pb is None or Pd is None:
            return None
        out['p_bubble'] = Pb / 1000.0
        out['p_dew'] = Pd / 1000.0
        out['hf'] = disp_h(cp_name, PropsSI('H', 'T', T, 'Q', 0, cp_name))
        out['hg'] = disp_h(cp_name, PropsSI('H', 'T', T, 'Q', 1, cp_name))
        out['sf'] = disp_s(cp_name, PropsSI('S', 'T', T, 'Q', 0, cp_name))
        out['sg'] = disp_s(cp_name, PropsSI('S', 'T', T, 'Q', 1, cp_name))
        out['rhof'] = PropsSI('D', 'T', T, 'Q', 0, cp_name)
        out['rhog'] = PropsSI('D', 'T', T, 'Q', 1, cp_name)
        out['latent'] = out['hg'] - out['hf']
    return out


def full_state(cp_name, k1, v1, k2, v2):
    """两个独立参数 → 全状态。内部 SI。"""
    st = {}
    T = PropsSI('T', k1, v1, k2, v2, cp_name)
    P = PropsSI('P', k1, v1, k2, v2, cp_name)
    st['T'] = T - 273.15
    st['P'] = P / 1000.0
    st['h'] = disp_h(cp_name, PropsSI('H', k1, v1, k2, v2, cp_name))
    st['s'] = disp_s(cp_name, PropsSI('S', k1, v1, k2, v2, cp_name))
    rho = PropsSI('D', k1, v1, k2, v2, cp_name)
    st['rho'] = rho
    st['v'] = 1.0 / rho if rho else None
    q = maybe(lambda: PropsSI('Q', k1, v1, k2, v2, cp_name))
    st['quality'] = q if (q is not None and 0.0 <= q <= 1.0) else None
    st['cp'] = maybe(lambda: PropsSI('C', k1, v1, k2, v2, cp_name) / 1000.0)
    st['cv'] = maybe(lambda: PropsSI('O', k1, v1, k2, v2, cp_name) / 1000.0)
    st['mu'] = maybe(lambda: PropsSI('V', k1, v1, k2, v2, cp_name) * 1e6)     # µPa·s
    st['k'] = maybe(lambda: PropsSI('L', k1, v1, k2, v2, cp_name) * 1000.0)   # mW/m·K
    # 相态判定
    Pcrit = crit(cp_name)['P']
    if P >= Pcrit * 0.999:
        st['phase'] = '超临界'
    elif st['quality'] is not None:
        st['phase'] = '两相（湿蒸气）'
    else:
        sat = sat_info(cp_name, P=P)
        if sat:
            if st['T'] >= sat['t_dew'] - 0.01:
                st['phase'] = '过热蒸气'
                st['superheat'] = st['T'] - sat['t_dew']
            else:
                st['phase'] = '过冷液体'
                st['subcool'] = sat['t_bubble'] - st['T']
        else:
            st['phase'] = '—'
    return st


# ---------------- API 处理 ----------------

def q1(qs, key, default=None, typ=float):
    v = qs.get(key, [None])[0]
    if v is None or v == '':
        if default is None:
            raise ValueError('缺少参数: %s' % key)
        return default
    return typ(v)


def api_health(qs):
    import CoolProp
    return {'ok': True, 'coolprop': CoolProp.__version__, 'fluids': list(FLUIDS.keys())}


def api_fluid_info(qs):
    f = q1(qs, 'fluid', typ=str)
    cn = cp_fluid(f)
    c = crit(cn)
    return {
        'fluid': f,
        't_crit': c['T'] - 273.15,
        'p_crit': c['P'] / 1000.0,
        'molar_mass': c['M'] * 1000.0,
        't_min': maybe(lambda: PropsSI('TMIN', cn) - 273.15),
        'glide_blend': f in GLIDE_BLENDS,
    }


def api_props(qs):
    f = q1(qs, 'fluid', typ=str)
    cn = cp_fluid(f)
    pair = q1(qs, 'pair', typ=str)        # TP TQ PQ PH PS
    v1 = q1(qs, 'v1')
    v2 = q1(qs, 'v2')

    def conv(letter, val):
        if letter == 'T':
            return 'T', val + 273.15
        if letter == 'P':
            return 'P', val * 1000.0
        if letter == 'Q':
            return 'Q', val
        if letter == 'H':
            return 'H', si_h(cn, val)
        if letter == 'S':
            return 'S', si_s(cn, val)
        if letter == 'D':
            return 'D', val
        raise ValueError('不支持的参数: %s' % letter)

    k1, sv1 = conv(pair[0], v1)
    k2, sv2 = conv(pair[1], v2)

    # T+P 在两相区不独立 → 给出提示与饱和数据
    if pair in ('TP', 'PT'):
        Tval = sv1 if k1 == 'T' else sv2
        Pval = sv1 if k1 == 'P' else sv2
        sat = sat_info(cn, P=Pval)
        if sat and sat['t_bubble'] - 0.05 < Tval - 273.15 < sat['t_dew'] + 0.05:
            return {'two_phase_ambiguous': True, 'sat': sat,
                    'hint': '该温压组合位于两相区，温度与压力不独立；请改用 压力+干度 或 温度+干度 查询。'}

    st = full_state(cn, k1, sv1, k2, sv2)
    st['sat_at_p'] = sat_info(cn, P=st['P'] * 1000.0)
    if st['T'] + 273.15 < crit(cn)['T']:
        st['sat_at_t'] = sat_info(cn, T=st['T'] + 273.15)
    st['fluid'] = f
    return st


def api_sat(qs):
    f = q1(qs, 'fluid', typ=str)
    cn = cp_fluid(f)
    by = q1(qs, 'by', typ=str)
    if by == 'T':
        T = q1(qs, 'value') + 273.15
        sat = sat_info(cn, T=T)
    else:
        P = q1(qs, 'value') * 1000.0
        sat = sat_info(cn, P=P)
    if sat is None:
        raise ValueError('超出饱和范围（可能高于临界点）')
    sat['fluid'] = f
    return sat


def api_sat_table(qs):
    """整张饱和表：T 从 t1 到 t2 步长 dt"""
    f = q1(qs, 'fluid', typ=str)
    cn = cp_fluid(f)
    t1 = q1(qs, 't1', -40.0)
    t2 = q1(qs, 't2', 60.0)
    dt = max(q1(qs, 'dt', 10.0), 1.0)
    tcrit = crit(cn)['T'] - 273.15
    rows = []
    t = t1
    while t <= t2 + 1e-6 and t < tcrit - 1:
        s = sat_info(cn, T=t + 273.15)
        if s:
            s['t'] = t
            rows.append(s)
        t += dt
    return {'fluid': f, 'rows': rows}


def api_dome(qs):
    f = q1(qs, 'fluid', typ=str)
    cn = cp_fluid(f)
    Pc = crit(cn)['P']
    Pt = max(maybe(lambda: PropsSI('PMIN', cn)) or 20000.0, 20000.0)
    n = 70
    Ps, hfs, hgs, Ts = [], [], [], []
    for i in range(n):
        P = Pt * (Pc * 0.995 / Pt) ** (i / (n - 1.0))
        hf = maybe(lambda: disp_h(cn, PropsSI('H', 'P', P, 'Q', 0, cn)))
        hg = maybe(lambda: disp_h(cn, PropsSI('H', 'P', P, 'Q', 1, cn)))
        td = maybe(lambda: PropsSI('T', 'P', P, 'Q', 1, cn))
        if hf is None or hg is None:
            continue
        Ps.append(P / 1000.0)
        hfs.append(hf)
        hgs.append(hg)
        Ts.append(td - 273.15 if td is not None else None)
    return {'fluid': f, 'p': Ps, 'hf': hfs, 'hg': hgs, 't': Ts,
            't_crit': crit(cn)['T'] - 273.15, 'p_crit': Pc / 1000.0}


def api_phcycle(qs):
    """理论单级循环: 蒸发/冷凝压力(kPa) + 过热/过冷 + 等熵效率 [+ 流量]"""
    f = q1(qs, 'fluid', typ=str)
    cn = cp_fluid(f)
    pe = q1(qs, 'pe') * 1000.0
    pc = q1(qs, 'pc') * 1000.0
    sh = q1(qs, 'sh', 5.0)
    sc = q1(qs, 'sc', 5.0)
    eff = min(max(q1(qs, 'eff', 0.70), 0.3), 1.0)
    mdot = q1(qs, 'mdot', 0.0)            # g/s，0 = 不给
    if pc <= pe * 1.01:
        raise ValueError('冷凝压力必须高于蒸发压力')

    t_dew_e = PropsSI('T', 'P', pe, 'Q', 1, cn)
    t_bub_c = PropsSI('T', 'P', pc, 'Q', 0, cn)

    # 点1 吸气
    if sh > 0.01:
        h1 = PropsSI('H', 'P', pe, 'T', t_dew_e + sh, cn)
        s1 = PropsSI('S', 'P', pe, 'T', t_dew_e + sh, cn)
        rho1 = PropsSI('D', 'P', pe, 'T', t_dew_e + sh, cn)
        T1 = t_dew_e + sh
    else:
        h1 = PropsSI('H', 'P', pe, 'Q', 1, cn)
        s1 = PropsSI('S', 'P', pe, 'Q', 1, cn)
        rho1 = PropsSI('D', 'P', pe, 'Q', 1, cn)
        T1 = t_dew_e
    # 点2s / 点2
    h2s = PropsSI('H', 'P', pc, 'S', s1, cn)
    h2 = h1 + (h2s - h1) / eff
    T2 = PropsSI('T', 'P', pc, 'H', h2, cn)
    # 点3 冷凝出口
    if sc > 0.01:
        h3 = PropsSI('H', 'P', pc, 'T', t_bub_c - sc, cn)
        T3 = t_bub_c - sc
    else:
        h3 = PropsSI('H', 'P', pc, 'Q', 0, cn)
        T3 = t_bub_c
    # 点4
    h4 = h3
    q4 = maybe(lambda: PropsSI('Q', 'P', pe, 'H', h4, cn))
    T4 = PropsSI('T', 'P', pe, 'H', h4, cn)

    qe = (h1 - h4) / 1000.0
    qc = (h2 - h3) / 1000.0
    w = (h2 - h1) / 1000.0
    out = {
        'fluid': f,
        't_evap_dew': t_dew_e - 273.15, 't_cond_bubble': t_bub_c - 273.15,
        'points': {
            '1': {'T': T1 - 273.15, 'P': pe / 1000, 'h': disp_h(cn, h1), 's': disp_s(cn, s1)},
            '2s': {'T': PropsSI('T', 'P', pc, 'H', h2s, cn) - 273.15, 'P': pc / 1000, 'h': disp_h(cn, h2s)},
            '2': {'T': T2 - 273.15, 'P': pc / 1000, 'h': disp_h(cn, h2)},
            '3': {'T': T3 - 273.15, 'P': pc / 1000, 'h': disp_h(cn, h3)},
            '4': {'T': T4 - 273.15, 'P': pe / 1000, 'h': disp_h(cn, h4), 'x': q4},
        },
        'qe': qe, 'qc': qc, 'w': w,
        'cop_c': qe / w, 'cop_h': qc / w,
        'pr': pc / pe, 'rho_suction': rho1,
        'vol_capacity': qe * rho1,        # kJ/m³ 容积制冷量
    }
    if mdot > 0:
        m = mdot / 1000.0
        out['mdot'] = mdot
        out['Qe_kW'] = qe * m
        out['Qc_kW'] = qc * m
        out['W_kW'] = w * m
    return out


def api_psychro(qs):
    """湿空气：给定大气压 + 两个参数 → 全状态"""
    P = q1(qs, 'p', 101.325) * 1000.0
    keymap = {'tdb': 'T', 'twb': 'B', 'tdp': 'D', 'rh': 'R', 'w': 'W', 'h': 'H'}
    given = []
    for k in keymap:
        raw = qs.get(k, [None])[0]
        if raw not in (None, ''):
            v = float(raw)
            if k in ('tdb', 'twb', 'tdp'):
                v += 273.15
            elif k == 'rh':
                v /= 100.0
            elif k == 'w':
                v /= 1000.0
            elif k == 'h':
                v *= 1000.0
            given.append((keymap[k], v))
    if len(given) != 2:
        raise ValueError('请提供恰好两个已知参数（当前 %d 个）' % len(given))
    a, b = given

    def get(out):
        return HAPropsSI(out, a[0], a[1], b[0], b[1], 'P', P)

    Tdb = get('T')
    out = {
        'p': P / 1000.0,
        'tdb': Tdb - 273.15,
        'twb': get('B') - 273.15,
        'tdp': get('D') - 273.15,
        'rh': get('R') * 100.0,
        'w': get('W') * 1000.0,                    # g/kg干空气
        'h': get('H') / 1000.0,                    # kJ/kg干空气
        'v': get('V'),                             # m³/kg干空气
        'p_w': get('P_w') / 1000.0,                # 水蒸气分压 kPa
        'p_ws': HAPropsSI('P_w', 'T', Tdb, 'R', 1.0, 'P', P) / 1000.0,
    }
    out['rho'] = (1.0 + out['w'] / 1000.0) / out['v']   # 湿空气密度
    return out


def api_watersat(qs):
    """水蒸气饱和性质 T↔P"""
    by = q1(qs, 'by', typ=str)
    if by == 'T':
        T = q1(qs, 'value') + 273.15
        P = PropsSI('P', 'T', T, 'Q', 0, 'Water')
        return {'t': T - 273.15, 'p_sat': P / 1000.0}
    P = q1(qs, 'value') * 1000.0
    T = PropsSI('T', 'P', P, 'Q', 0, 'Water')
    return {'p': P / 1000.0, 't_sat': T - 273.15}


def api_liquid(qs):
    """水/乙二醇溶液 输送介质物性"""
    f = q1(qs, 'fluid', 'water', typ=str)
    T = q1(qs, 't', 7.0) + 273.15
    name = {'water': 'Water', 'meg30': 'INCOMP::MEG[0.30]', 'meg50': 'INCOMP::MEG[0.50]'}.get(f)
    if not name:
        raise ValueError('介质仅支持 water / meg30 / meg50')
    P = 300000.0
    return {
        'fluid': f, 't': T - 273.15,
        'rho': PropsSI('D', 'T', T, 'P', P, name),
        'mu': PropsSI('V', 'T', T, 'P', P, name) * 1000.0,    # mPa·s
        'cp': PropsSI('C', 'T', T, 'P', P, name) / 1000.0,    # kJ/kg·K
        'k': maybe(lambda: PropsSI('L', 'T', T, 'P', P, name)),
    }


# ---------------------------------------------------------------
# Supabase Edge Function 同源代理：国内浏览器直连 supabase.co 不稳定（GFW/CORS），
# 改走 页面同源 /api/fn/<name>（或旧别名 /api/register）→ 本服务器（新加坡）→ Supabase。
# 同源请求无 CORS 预检；Authorization 透传（后台需调用者 JWT），未带则用公开 publishable key。
# 仅白名单函数可转发，避免开放代理。
# ---------------------------------------------------------------
SB_FUNC_BASE = 'https://lnzepjubgtdclvmridxw.supabase.co/functions/v1/'
SB_PUB_KEY = 'sb_publishable_m4cNAyw4SzOdv-eogmOsDg_kHicDMEf'
SB_FN_ALLOW = {'register-with-invite', 'admin-api'}


def proxy_function(name, payload, auth_header=None):
    """转发到 Edge Function；连接级失败重试 3 次，HTTP 业务错误（4xx/5xx）原样透传不重试。"""
    last_err = None
    for attempt in range(3):
        req = urllib.request.Request(SB_FUNC_BASE + name, data=payload, method='POST', headers={
            'Content-Type': 'application/json',
            'apikey': SB_PUB_KEY,
            'Authorization': auth_header or ('Bearer ' + SB_PUB_KEY),
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.getcode(), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:
            last_err = e
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError('upstream unreachable: %s' % last_err)


ROUTES = {
    '/api/health': api_health,
    '/api/fluidinfo': api_fluid_info,
    '/api/props': api_props,
    '/api/sat': api_sat,
    '/api/sattable': api_sat_table,
    '/api/dome': api_dome,
    '/api/phcycle': api_phcycle,
    '/api/psychro': api_psychro,
    '/api/watersat': api_watersat,
    '/api/liquid': api_liquid,
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        # 本地工具站：禁止缓存，避免版本更新后浏览器用旧文件
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ROUTES:
            try:
                data = ROUTES[u.path](parse_qs(u.query))
                body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
                code = 200
            except ValueError as e:
                body = json.dumps({'error': str(e)}, ensure_ascii=False).encode('utf-8')
                code = 400
            except Exception as e:
                traceback.print_exc()
                body = json.dumps({'error': '计算失败: %s' % str(e)[:200],
                                   'hint': '请检查输入是否超出物性有效范围'}, ensure_ascii=False).encode('utf-8')
                code = 500
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        fn = None
        if u.path == '/api/register':               # 旧别名，等价 /api/fn/register-with-invite
            fn = 'register-with-invite'
        elif u.path.startswith('/api/fn/'):
            cand = u.path[len('/api/fn/'):]
            if cand in SB_FN_ALLOW:
                fn = cand
        if fn:
            try:
                n = int(self.headers.get('Content-Length') or 0)
                if n <= 0 or n > 100000:
                    raise ValueError('bad content length')
                payload = self.rfile.read(n)
                code, body = proxy_function(fn, payload, self.headers.get('Authorization'))
            except Exception:
                body = json.dumps({'error': 'proxy_unavailable'}).encode('utf-8')
                code = 502
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # 未知路径：先读掉请求体再响应，避免连接被 RST（客户端收不到 404）
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if 0 < n <= 100000:
                self.rfile.read(n)
        except Exception:
            pass
        body = json.dumps({'error': 'not found'}).encode('utf-8')
        self.send_response(404)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    print('HVAC 工具站: http://127.0.0.1:%d  (Ctrl+C 停止)' % PORT)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
