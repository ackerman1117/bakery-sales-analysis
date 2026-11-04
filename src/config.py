"""全局配置：路径、输入/输出表名、单位换算与经营参数。

数据模型原则：
- 唯一事实表：购买记录（订单明细），所有经营指标都由它派生。
- 维度表：商品原料信息（配方 BOM）、日期维度表；原材料信息为可选维度。
- 其余结果全部由代码计算，不从原始 Excel 读取。
"""

from pathlib import Path

# ---------- 路径 ----------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw" / "food.xlsx"
DATA_SAMPLE = BASE_DIR / "data" / "sample" / "sample_food.xlsx"
OUT_TABLES = BASE_DIR / "outputs" / "tables"
OUT_FIGURES = BASE_DIR / "outputs" / "figures"

# ---------- 输入 sheet 名 ----------
SHEET_PURCHASE = "购买记录"
SHEET_BOM = "商品原料信息"
SHEET_DATE_DIM = "日期维度表"

SHEET_MATERIAL = "原材料信息"                 # 可选：用于成本、包装规格、单位推断
SHEET_ACTUAL_CONSUMPTION = "原料实际消耗"     # 可选：用于实际 vs 理论消耗对比

REQUIRED_SHEETS = [SHEET_PURCHASE, SHEET_BOM, SHEET_DATE_DIM]
OPTIONAL_SHEETS = [SHEET_MATERIAL, SHEET_ACTUAL_CONSUMPTION]

# 这些 sheet 目前不参与计算：部分是别人已经算好的结果（口径不一致），
# 产品生产 / 原材料明细属于以后才接入的数据，现在按「暂不需要」处理。
IGNORED_SHEETS = [
    "原料消耗",
    "单日产品销售量",
    "原料采购",
    "客流量",
    "口味偏好",
    "产品偏好",
    "产品生产",
    "字段分析建议",
]

# ---------- 购买记录必需字段 ----------
PURCHASE_REQUIRED_COLUMNS = ["时间", "身份id", "单号", "产品", "数量", "消费金额", "日期"]

# ---------- 编码映射 ----------
# 口味风格编码：口径来自「商品原料信息」
TASTE_MAP = {1: "甜味", 2: "咸味"}

# ---------- 单位换算 ----------
# BOM「重量」未写单位时，按原料形态推断：液体 → ml，其余 → g。
# 换算目标：固体统一为 kg，液体统一为 L。
UNIT_FACTORS = {
    "g": ("kg", 0.001),
    "克": ("kg", 0.001),
    "kg": ("kg", 1.0),
    "千克": ("kg", 1.0),
    "ml": ("L", 0.001),
    "毫升": ("L", 0.001),
    "l": ("L", 1.0),
    "升": ("L", 1.0),
}
LIQUID_UNITS = {"l", "升", "ml", "毫升"}
DEFAULT_SOLID_UNIT = "g"
DEFAULT_LIQUID_UNIT = "ml"

# ---------- 经营参数（排班 / 补货） ----------
# 一名小时工每小时可服务的客流人次；用于把客流换算成在岗人数。
SERVICE_CAPACITY_PER_HOUR = 15
# 小时工工资（元/小时）；设为 None 则不输出人力成本列。
HOURLY_WAGE = 30.0
# 安全库存天数：建议采购量 = 预计消耗 + 日均消耗 × 安全库存天数。
SAFETY_STOCK_DAYS = 3
# 采购建议向前覆盖的月份数（从数据最后一天的下一个月开始）。
PURCHASE_FORECAST_MONTHS = 3
