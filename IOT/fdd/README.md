# FDD M0 初始化包

先读 CLAUDE.md(铁律)。测试即规格:仓库初始状态 `pytest -m m0` 全红,M0 完成的定义 = 全绿。

    pip install -e ".[dev]" && python scripts/smoke.py && pytest -m m0

模块实现顺序建议:conv → seg → zoho_v2(zoho_v2 的修复 #8 在拿到 SN 编码规则前以 passthrough 模式实现)。
真实 Zoho 导出与队列遥测数据禁止进入本仓库(见 data/README.md)。
