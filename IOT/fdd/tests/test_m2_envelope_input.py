"""
FDD-I-018 · envelope_input／rating_anchor 拆分单元测试(规格层,方案侧起草)
===================================================================
测试即规格:钉死 NONSTD_HEAT 双规则。CC 实现到全绿,不得改本文件(铁律 11/12)。

【放置前对齐(同 FDD-I-016 经验,grep 自证)】
1. 导入:按实际模块路径改(anchor 派生逻辑可能在 c4.py 或 baseline.py 装配处)。
2. 本测试对 c4 加载后的 lab DataFrame 断言两列布尔;若拆分以别的载体实现
   (如两个 mask 函数),按实际接口调整取值方式,断言语义不变。
3. 字符串常量 NONSTD_HEAT / fault_injected 与代码实际值对齐(改顶部常量一处)。

契约:c4 加载产出的 lab 表每行有两独立布尔列 rating_anchor / envelope_input。
"""

import pytest

# ← 按实际改:构造/加载出一个含各类行的 lab 表的接口
from fdd.c4 import load_lab_for_test  # 占位:或用现有 lab fixture

pytestmark = pytest.mark.m2

RATING = "rating_anchor"
ENVIN = "envelope_input"
NONSTD = "NONSTD_HEAT"
FAULT = "fault_injected"


@pytest.fixture
def lab():
    # 期望该 fixture/加载器返回含以下三类稳态锚行的表:
    # (a) 健康标准工况稳态行(如 H1 clean_steady, data_type=healthy_baseline)
    # (b) NONSTD_HEAT 稳态行(19.4℃ 制热健康数据)
    # (c) fault_injected 行(31 号少冷媒)
    return load_lab_for_test()


# ── 规则①:NONSTD 出额定锚池 ────────────────────────────────────────
def test_nonstd_excluded_from_rating_anchor(lab):
    nonstd = lab[lab["ahri_condition"] == NONSTD]
    assert len(nonstd) > 0, "测试前提:表中须有 NONSTD_HEAT 稳态行"
    assert (~nonstd[RATING]).all(), "规则①:NONSTD_HEAT 行 rating_anchor 必须全 False"


# ── 规则②:NONSTD 留 envelope 拟合输入 ──────────────────────────────
def test_nonstd_retained_as_envelope_input(lab):
    nonstd_steady = lab[(lab["ahri_condition"] == NONSTD) & lab["is_steady_anchor"]]
    assert len(nonstd_steady) > 0, "测试前提:须有 NONSTD_HEAT 稳态锚行"
    assert nonstd_steady[ENVIN].all(), "规则②:NONSTD_HEAT 稳态行 envelope_input 必须全 True"


# ── 两列确实解耦(对 NONSTD 取值相反,不是同一布尔别名)──────────────
def test_two_columns_decoupled_on_nonstd(lab):
    nonstd_steady = lab[(lab["ahri_condition"] == NONSTD) & lab["is_steady_anchor"]]
    # anchor=False 而 input=True,证明两列非同义
    assert (nonstd_steady[RATING] != nonstd_steady[ENVIN]).all(), \
        "NONSTD 稳态行两列须相反(anchor=False, input=True),否则拆分未生效"


# ── 健康标准工况稳态行:两列同 True(行为不变)──────────────────────
def test_healthy_standard_rows_both_true(lab):
    healthy = lab[(lab["data_type"] == "healthy_baseline")
                  & (lab["ahri_condition"] != NONSTD)
                  & lab["is_steady_anchor"]]
    assert len(healthy) > 0
    assert healthy[RATING].all() and healthy[ENVIN].all(), \
        "健康标准工况稳态锚行两列须同 True(拆分不改其行为)"


# ── fault_injected 行:两列同 False(FDD-I-017 排除保持)──────────────
def test_fault_injected_excluded_from_both(lab):
    fault = lab[lab["data_type"] == FAULT]
    assert len(fault) > 0, "测试前提:表中须有 fault_injected 行(31 号)"
    assert (~fault[RATING]).all() and (~fault[ENVIN]).all(), \
        "fault_injected 行两列须全 False(既不额定也不进拟合)"


# ── envelope 拟合输入集合 = envelope_input,不再等于 rating_anchor ──
def test_fit_input_uses_envelope_input_not_rating(lab):
    fit_set = lab[lab[ENVIN]]
    rating_set = lab[lab[RATING]]
    # 拟合集须含 NONSTD 稳态行、额定集须不含 → 两集合不相等
    assert len(fit_set) != len(rating_set) or \
        not fit_set.index.equals(rating_set.index), \
        "拟合输入集合仍等于额定锚池,拆分未落实"
    # 拟合集含 NONSTD,额定集不含
    assert (fit_set["ahri_condition"] == NONSTD).any()
    assert not (rating_set["ahri_condition"] == NONSTD).any()
