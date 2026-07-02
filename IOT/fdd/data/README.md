# 数据放置规则(硬性)

- data/sample/       仅样本与字段字典(已含)。可入 git。
- data/raw/          真实队列遥测/实验室/产线数据落位处。禁入 git(.gitignore 已挡)。
- data/lake/         Parquet 分析湖(sn_hash/year/month 分区)。禁入 git。
- 禁止放入本仓库任何位置:含明文 SN 或客户 PII 的 Zoho 原始导出。
  Zoho 数据只允许以 v2 流水线的脱敏产物形态进入(无 normalized_sn 列)。
