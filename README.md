# 面包店数据分析 / Bakery Sales Analysis

> 面包店销售、生产、原料与客流数据分析项目：从原始 Excel 数据到可复用的分析结果。

一个面向小型面包店的经营数据分析框架。围绕 **销售 / 生产 / 原料 / 客流 / 口味偏好** 五个维度，
把日常流水数据加工成可支撑经营决策的指标与报表。

## 项目特点

- **数据模型清晰**：一张明细事实表 + 维度表 + 五张结果表，主外键统一（商品编号、原料编号、口味编码）
- **开箱即用**：仓库自带脱敏样例数据 `data/sample/sample_food.xlsx`，克隆后无需额外数据即可跑通全流程
- **模块化**：`load → clean → analysis` 三层分离，新增指标只需在 `analysis.py` 增加一个函数
- **结果落盘**：分析结果统一输出到 `outputs/tables/`（CSV），便于二次加工或喂给 BI 工具

## 目录结构

```
bakery-sales-analysis/
├── README.md
├── requirements.txt
├── .gitignore
├── data/
│   ├── raw/                  # 真实数据放这里（不入库）
│   └── sample/               # 样例数据（入库，保证项目可运行）
├── src/
│   ├── config.py             # 路径、sheet 名、口味编码等常量
│   ├── load.py               # 读取 Excel 各 sheet
│   ├── clean.py              # 日期统一、类型转换、节假日补全、金额校验
│   ├── analysis.py           # 各类分析指标
│   └── run_all.py            # 一键跑全部分析
├── notebooks/
│   └── 01_explore.ipynb      # 探索性分析
├── outputs/
│   ├── tables/               # 分析结果 CSV
│   └── figures/              # 图表
└── docs/
    └── data_dictionary.md    # 数据字典
```

## 快速开始

```bash
git clone <your-repo-url>
cd bakery-sales-analysis
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python -m src.run_all
```

运行后终端会打印各项分析结论，同时把明细结果写入 `outputs/tables/`。

使用自己的数据：

```bash
# 把你的 Excel 放到 data/raw/food.xlsx，然后
python -m src.run_all
```

程序优先读取 `data/raw/food.xlsx`，不存在时自动回退到样例数据。

## 数据模型

**事实表**：`购买记录`（订单明细）、`产品生产`、`原料消耗`

**维度表**：`商品原料信息`（配方 BOM）、`原材料信息`、`日期维度表`（2026 全年，含节假日/调休）

**结果表**：`单日产品销售量`、`原料采购`、`客流量`、`口味偏好`、`产品偏好`

字段定义、类型与关联关系见 [docs/data_dictionary.md](docs/data_dictionary.md)。

## 分析能力

| 模块 | 说明 |
|---|---|
| 销售概览 | 总销量、总销售额、日均、客单价、订单数 |
| 产品排名 | 各产品销量/销售额及占比排名 |
| 口味偏好 | 按口味编码聚合，甜/咸味销量与销售额对比 |
| 节假日效应 | 节假日 vs 工作日 的日均销售对比 |
| 生产与销售匹配 | 当日产量 vs 销量，识别备货不足或过剩 |
| 原料消耗 | 各原料总消耗量、日均消耗 |
| 采购 vs 消耗 | 按月比较采购量与消耗量，识别库存积压风险 |
| 客流分析 | 分时段消费人次、销售额、客单价、高峰时段 |

## 路线图

- [ ] 增加毛利分析（结合 BOM 用量 × 原料单价）
- [ ] 输出 HTML 看板（Streamlit / Plotly）
- [ ] 销售预测（按星期 + 节假日的时序模型）
- [ ] 数据校验规则（缺失值、外键完整性、金额一致性）

## 数据说明

仓库内 `data/sample/sample_food.xlsx` 为**模拟数据**，仅用于演示与测试，不代表任何真实门店经营情况。
真实数据请放在 `data/raw/`，该目录已在 `.gitignore` 中排除。

## License

MIT
