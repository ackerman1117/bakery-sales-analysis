"""全局配置：路径、sheet 名、编码映射。"""

from pathlib import Path

# ---------- 路径 ----------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw" / "food.xlsx"
DATA_SAMPLE = BASE_DIR / "data" / "sample" / "sample_food.xlsx"
OUT_TABLES = BASE_DIR / "outputs" / "tables"
OUT_FIGURES = BASE_DIR / "outputs" / "figures"

# ---------- sheet 名 ----------
SHEET_PURCHASE = "购买记录"
SHEET_PRODUCTION = "产品生产"
SHEET_BOM = "商品原料信息"
SHEET_MATERIAL = "原材料信息"
SHEET_CONSUMPTION = "原料消耗"
SHEET_DAILY_SALES = "单日产品销售量"
SHEET_PURCHASE_MONTHLY = "原料采购"
SHEET_TRAFFIC = "客流量"
SHEET_TASTE_PREF = "口味偏好"
SHEET_PRODUCT_PREF = "产品偏好"
SHEET_DATE_DIM = "日期维度表"

# 需要读取的全部业务 sheet（不含说明类 sheet）
BUSINESS_SHEETS = [
    SHEET_PURCHASE,
    SHEET_PRODUCTION,
    SHEET_BOM,
    SHEET_MATERIAL,
    SHEET_CONSUMPTION,
    SHEET_DAILY_SALES,
    SHEET_PURCHASE_MONTHLY,
    SHEET_TRAFFIC,
    SHEET_TASTE_PREF,
    SHEET_PRODUCT_PREF,
    SHEET_DATE_DIM,
]

# ---------- 编码映射 ----------
# 口味风格编码：与「商品原料信息」「产品生产」中的口径保持一致
TASTE_MAP = {1: "甜味", 2: "咸味"}

# 各表需要转为日期的列
DATE_COLUMNS = {
    SHEET_PURCHASE: ["日期"],
    SHEET_PRODUCTION: ["日期"],
    SHEET_CONSUMPTION: ["日期"],
    SHEET_DAILY_SALES: ["日期"],
    SHEET_TRAFFIC: ["日期"],
    SHEET_DATE_DIM: ["日期"],
}
