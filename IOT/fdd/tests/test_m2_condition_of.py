"""
FDD-I-016 · condition_of 单元测试(规格层,方案侧起草)
===================================================================
本文件是"测试即规格":定义 condition_of 的验收契约,CC 实现到全绿。
CC 不得修改本文件(铁律 11/12)。断言与实现冲突 = 改实现,不改测试。

【放置前 Alan 需用一条命令对齐的三点】
  grep -rn "def condition_of" src/ && grep -rn "def condition_of" -A 40 src/fdd/seg.py
上面输出一次给出:所在文件 / 函数签名 / 所有 return 字符串。据此对齐:

1. 导入路径:CLAUDE.md 契约摘要无 conditions.py,M-SEG=src/fdd/seg.py,强指向
   `from fdd.seg import condition_of`。若 grep 显示别处,改这一行。导入风格
   (fdd.seg vs src.fdd.seg)按现有 tests/test_m1_*.py 一致。
2. 第二参:CLAUDE.md 第46行现签名为 condition_of(Ta, mode)(第二参是 mode 不是
   is_heating)。FDD-I-016 建议保持 mode、只加 freq → condition_of(Ta, mode, freq)。
   把下方 MODE_HEAT/MODE_COOL 对齐 mode 字段的真实取值(grep 里的分支值)。
3. 返回字符串常量:
   - 置信类(CONFIDENT/AMBIGUOUS/UNKNOWN_CONDITION)= 已存在,被下游消费。若与代码
     实际大小写/拼写不一致,改本文件顶部常量去迁就代码(勿churn condition_of返回值)。
   - 字母类 = 测试驱动实现(H1N→H1、H22→H2、H4Full→H4、H12→NONSTD_HEAT 是 Item 1 目的)。
   - 容量类(FULL/UNKNOWN_CAPACITY)= 全新,测试定义。

【契约总述】
condition_of(Ta_c, mode, freq_hz) -> (letter, capacity, confidence)
- letter/confidence 由 Ta + mode 判。归属规则:取 ±1.5℃ 内最近的工况中心;
  无中心在 ±1.5℃ 内 → UNKNOWN_CONDITION。(最近中心法在非重叠工况上等价于落带法,
  仅用于裁决 H0 16.7℃ / NONSTD_HEAT 19.4℃ 这一处 0.3℃ 重叠。)
- capacity 由实际频率判,与 letter 正交(letter=UNKNOWN 时 capacity 仍照算)。
- 频率口径:本测试用 lab InvHz(Hz)。现场 CompRps 另一套阈值,不在本测试范围。
- NONSTD_HEAT:19.4℃(67°F)制热,非 AHRI 标准工况、是实验室验证点。condition_of
  只负责打此标签;"排除额定锚/保留 envelope/不进异常清单"是下游规则,不在本单元测试。
- 非稳态/特殊模式(除霜/回油)由 M-SEG 前置剔除,condition_of 只见制热/制冷稳态行。
"""

import pytest

from fdd.c4 import condition_of  # ← 按 grep 结果对齐:实际位于 c4.py:137(M2-C4 判定层),非 seg

pytestmark = pytest.mark.m2

# ── 期望返回字符串常量(与代码对齐,改这里一处)────────────────────────
CONFIDENT = "confident"
AMBIGUOUS = "AMBIGUOUS"
UNKNOWN_CONDITION = "UNKNOWN_CONDITION"
FULL = "Full"
UNKNOWN_CAPACITY = "UNKNOWN_CAPACITY"

# ── mode 字段真实取值(对齐 grep 里的分支值)──────────────────────────
MODE_HEAT = "heat"   # ← 已对齐 mode 字段的制热取值(c4 分支值 "heat")
MODE_COOL = "cool"   # ← 已对齐 mode 字段的制冷取值(c4 分支值 "cool")

# ── 工况-温度权威对应(AHRI 210/240-2026 Table 8,单位℃)──────────────
# 容差 ±1.5℃(AHRI 干球±0.56 + 记录±1)。NONSTD_HEAT=实验室非标准制热点。
COND_CENTER = {
    "A_or_A2": 35.0,       # 95°F 制冷,A/A2 靠容量不可分 → AMBIGUOUS
    "B":       27.8,       # 82°F 制冷
    "C_or_D":  19.4,       # 67°F 制冷,C/D 靠稳态/循环不可分 → AMBIGUOUS
    "H0":      16.7,       # 62°F 制热(当前无数据,仍是合法带;与 NONSTD 重叠靠最近中心裁决)
    "H1":       8.3,       # 47°F 制热
    "H2":       1.7,       # 35°F 制热
    "H3":      -8.3,       # 17°F 制热(当前 2436AA 无数据)
    "H4":     -15.0,       # 5°F  制热
    "NONSTD_HEAT": 19.4,   # 67°F 制热,非 AHRI 标准,实验室验证点
}
COND_MODE = {  # 每工况所属模式(19.4℃ 在 C_or_D 制冷 与 NONSTD_HEAT 制热 各出现一次,靠 mode 分)
    "A_or_A2": MODE_COOL, "B": MODE_COOL, "C_or_D": MODE_COOL,
    "H0": MODE_HEAT, "H1": MODE_HEAT, "H2": MODE_HEAT, "H3": MODE_HEAT,
    "H4": MODE_HEAT, "NONSTD_HEAT": MODE_HEAT,
}
AMBIGUOUS_LETTERS = {"A_or_A2", "C_or_D"}

# ── 全负荷频率带(Alan 认可,lab InvHz/Hz,闭区间)──────────────────────
FULL_BAND = {MODE_COOL: (66.0, 76.0), MODE_HEAT: (70.0, 86.0)}


# ===================================================================
# 组 1 · 各工况中心 Ta → 正确字母 + 正确置信
# ===================================================================
@pytest.mark.parametrize("letter", list(COND_CENTER.keys()))
def test_center_ta_maps_to_letter(letter):
    ta = COND_CENTER[letter]
    mode = COND_MODE[letter]
    got_letter, _cap, conf = condition_of(ta, mode, 72.0)  # 72Hz 落两模式带内
    assert got_letter == letter
    assert conf == (AMBIGUOUS if letter in AMBIGUOUS_LETTERS else CONFIDENT)


# ===================================================================
# 组 2 · 容差边界:±1.5℃ 闭区间命中,±1.6℃ 落空隙 → UNKNOWN_CONDITION
# ===================================================================
@pytest.mark.parametrize("letter", ["B", "H1", "H2", "H4"])
def test_tolerance_edges_inclusive(letter):
    c, mode = COND_CENTER[letter], COND_MODE[letter]
    assert condition_of(c - 1.5, mode, 72.0)[0] == letter
    assert condition_of(c + 1.5, mode, 72.0)[0] == letter

@pytest.mark.parametrize("letter", ["H1", "H2"])  # H1↔H2 空隙最窄(3.6℃),1.6 偏移不串档
def test_just_outside_tolerance_is_unknown(letter):
    c, mode = COND_CENTER[letter], COND_MODE[letter]
    lo = condition_of(c - 1.6, mode, 72.0)
    hi = condition_of(c + 1.6, mode, 72.0)
    assert lo[0] == UNKNOWN_CONDITION or lo[2] == UNKNOWN_CONDITION
    assert hi[0] == UNKNOWN_CONDITION or hi[2] == UNKNOWN_CONDITION


# ===================================================================
# 组 3 · 空隙 / 越界 → UNKNOWN_CONDITION(未注册点,不归属)
# ===================================================================
@pytest.mark.parametrize("ta,mode,why", [
    (5.0,  MODE_HEAT, "H1↔H2 空隙"),
    (12.0, MODE_HEAT, "H1↔H0 空隙(未注册,区别于已注册的 NONSTD 19.4)"),
    (23.0, MODE_COOL, "B↔C_or_D 空隙"),
    (31.0, MODE_COOL, "A↔B 空隙"),
    (-20.0, MODE_HEAT, "低于 H4,越界(FDD-I-015 同结论)"),
    (40.0, MODE_COOL, "高于 A,越界"),
])
def test_gaps_and_out_of_range_unknown(ta, mode, why):
    letter, _cap, conf = condition_of(ta, mode, 72.0)
    assert letter == UNKNOWN_CONDITION or conf == UNKNOWN_CONDITION, why


# ===================================================================
# 组 4 · 19.4℃ 跨模式撞点 + H0/NONSTD 重叠(最近中心裁决)
#   制冷 → C_or_D(AMBIGUOUS);制热 → NONSTD_HEAT(confident,非 AHRI 标准点)
#   ★ NONSTD_HEAT 是本轮规格决策;若改判为其它标签,改这三条
# ===================================================================
def test_194_cooling_is_C_or_D():
    letter, _cap, conf = condition_of(19.4, MODE_COOL, 71.0)
    assert letter == "C_or_D" and conf == AMBIGUOUS

def test_194_heating_is_nonstd():
    letter, _cap, conf = condition_of(19.4, MODE_HEAT, 78.0)
    assert letter == "NONSTD_HEAT" and conf == CONFIDENT

def test_h0_nonstd_nearest_center_tiebreak():
    # H0(16.7)与 NONSTD(19.4)带重叠 [17.9,18.2],中点 18.05,靠最近中心裁决
    assert condition_of(16.7, MODE_HEAT, 78.0)[0] == "H0"
    assert condition_of(19.4, MODE_HEAT, 78.0)[0] == "NONSTD_HEAT"
    assert condition_of(18.0, MODE_HEAT, 78.0)[0] == "H0"           # 距 H0 1.3 < 距 NONSTD 1.4
    assert condition_of(18.1, MODE_HEAT, 78.0)[0] == "NONSTD_HEAT"  # 距 NONSTD 1.3 < 距 H0 1.4


# ===================================================================
# 组 5 · 容量判定:频率在 Full 带(闭区间)→ Full,带外 → UNKNOWN_CAPACITY
#   带外含两侧:低于下界(部分负荷)+ 高于上界(异常/超速,不自扩带,Item3c 报出后人工调)
# ===================================================================
@pytest.mark.parametrize("mode,freq,expected,why", [
    (MODE_HEAT, 78.0, FULL,             "制热带[70,86]内"),
    (MODE_HEAT, 70.0, FULL,             "下沿闭区间"),
    (MODE_HEAT, 86.0, FULL,             "上沿闭区间"),
    (MODE_HEAT, 76.0, FULL,             "H1 实测全负荷(2436AA)"),
    (MODE_HEAT, 69.0, UNKNOWN_CAPACITY, "低于下界,部分负荷"),
    (MODE_HEAT, 45.0, UNKNOWN_CAPACITY, "明显部分负荷"),
    (MODE_HEAT, 87.0, UNKNOWN_CAPACITY, "高于上界,异常(不自扩带)"),
    (MODE_COOL, 71.0, FULL,             "制冷带[66,76]内"),
    (MODE_COOL, 66.0, FULL,             "下沿闭区间"),
    (MODE_COOL, 76.0, FULL,             "上沿闭区间"),
    (MODE_COOL, 65.0, UNKNOWN_CAPACITY, "低于下界"),
    (MODE_COOL, 40.0, UNKNOWN_CAPACITY, "明显部分负荷"),
    (MODE_COOL, 77.0, UNKNOWN_CAPACITY, "高于上界,异常"),
])
def test_capacity_by_freq_band(mode, freq, expected, why):
    ta = COND_CENTER["H1"] if mode == MODE_HEAT else COND_CENTER["B"]
    _letter, cap, _conf = condition_of(ta, mode, freq)
    assert cap == expected, why

def test_missing_freq_is_unknown_capacity():
    _l, cap_nan, _c = condition_of(COND_CENTER["H1"], MODE_HEAT, float("nan"))
    _l, cap_none, _c2 = condition_of(COND_CENTER["H1"], MODE_HEAT, None)
    assert cap_nan == UNKNOWN_CAPACITY and cap_none == UNKNOWN_CAPACITY


# ===================================================================
# 组 6 · letter × capacity 正交
# ===================================================================
def test_h1_full_anchor_case():
    # 2436AA H1 全负荷锚典型行:47°F 制热 + 76Hz → (H1, Full, confident)
    assert condition_of(8.3, MODE_HEAT, 76.0) == ("H1", FULL, CONFIDENT)

def test_ambiguous_letter_with_full_capacity():
    letter, cap, conf = condition_of(35.0, MODE_COOL, 71.0)
    assert letter == "A_or_A2" and cap == FULL and conf == AMBIGUOUS

def test_capacity_orthogonal_to_unknown_condition():
    # 12.0℃ 制热是真空隙(UNKNOWN_CONDITION);容量轴独立,freq 78Hz 仍判 Full
    letter, cap, conf = condition_of(12.0, MODE_HEAT, 78.0)
    assert (letter == UNKNOWN_CONDITION or conf == UNKNOWN_CONDITION)
    assert cap == FULL


# ===================================================================
# 组 7 · 频率不串字母 + 模式选对频率带(回归护栏)
# ===================================================================
def test_freq_does_not_shift_letter():
    assert condition_of(8.3, MODE_HEAT, 76.0)[0] == condition_of(8.3, MODE_HEAT, 45.0)[0] == "H1"

def test_mode_selects_correct_freq_band():
    assert condition_of(COND_CENTER["B"], MODE_COOL, 72.0)[1] == FULL
    assert condition_of(COND_CENTER["H1"], MODE_HEAT, 72.0)[1] == FULL
    assert condition_of(COND_CENTER["H1"], MODE_HEAT, 78.0)[1] == FULL            # 制热[70,86]内
    assert condition_of(COND_CENTER["B"], MODE_COOL, 78.0)[1] == UNKNOWN_CAPACITY # 制冷[66,76]外
