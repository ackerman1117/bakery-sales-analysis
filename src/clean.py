"""数据清洗层：日期统一、类型转换、节假日补全、金额校验。"""

import re
from typing import Dict, Optional

import pandas as pd


def to_date(value):
    """把混杂格式的日期值统一为 Timestamp。

    支持：datetime、20261201、'20261201'、'2026-12-01'、'2026/12/1'。
    无法识别（如 '1月'、202612）时返回 NaT，交由调用方按月份单独处理。
    """
    if pd.isna(value):
        return pd.NaT
    if isinstance(value, (pd.Timestamp,)):
        return value

    text = str(value).strip()
    # 纯数字 / 数字字符串：8 位视为 YYYYMMDD
    digits = re.sub(r"\D", "", text)
    if text.replace(".0", "").isdigit() or digits == text:
        if len(digits) == 8:
            return pd.to_datetime(digits, format="%Y%m%d", errors="coerce")
        return pd.NaT  # 6 位（YYYYMM）等不完整日期
    return pd.to_datetime(text, errors="coerce")


def normalize_dates(df: pd.DataFrame, columns) -> pd.DataFrame:
    """把指定列转为标准日期类型。"""
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].map(to_date)
    return out


def parse_month(value):
    """从 '1月' / '2026-01' / 202601 提取月份数字（1-12），失败返回 NA。"""
    if pd.isna(value):
        return pd.NA
    text = str(value)
    m = re.search(r"(\d{1,2})\s*月", text)
    if m:
        return int(m.group(1))
    digits = re.sub(r"\D", "", text)
    if len(digits) in (6, 8):
        return int(digits[4:6])
    if digits.isdigit() and 1 <= int(digits) <= 12:
        return int(digits)
    return pd.NA


def attach_holiday(df: pd.DataFrame, date_dim: pd.DataFrame,
                   date_col: str = "日期",
                   holiday_col: str = "节假日") -> pd.DataFrame:
    """用日期维度表补全/校验节假日标记。"""
    if df.empty or date_dim.empty or date_col not in df.columns:
        return df

    out = df.copy()
    dim = date_dim[[date_col, "是否节假日"]].copy()
    dim[date_col] = dim[date_col].map(to_date)
    dim = dim.dropna(subset=[date_col]).drop_duplicates(subset=[date_col])

    merged = out.merge(dim, on=date_col, how="left", suffixes=("", "_维度"))
    flag = merged["是否节假日"].fillna("否")
    # 维度表为准；维度表缺失时保留原值
    original = merged[holiday_col] if holiday_col in merged.columns else pd.Series("否", index=merged.index)
    merged[holiday_col] = flag.where(flag.notna(), original)
    return merged.drop(columns=["是否节假日"])


def enrich_purchases(df: pd.DataFrame, bom: pd.DataFrame) -> pd.DataFrame:
    """为购买记录补充商品名称与单价，并校验金额 = 数量 x 单价。"""
    if df.empty:
        return df

    out = df.copy()
    prices = (bom.groupby("商品编号")["商品名称"].first().reset_index())
    out = out.merge(prices, left_on="产品", right_on="商品编号", how="left")

    # 单价从金额/数量反推（样例数据未单独存单价）
    out["单价"] = (out["消费金额"] / out["数量"]).round(2)
    return out


def clean_all(frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """对全部表做统一清洗。"""
    from . import config

    out = dict(frames)
    dim = frames.get(config.SHEET_DATE_DIM, pd.DataFrame())

    for sheet, cols in config.DATE_COLUMNS.items():
        if sheet in out and not out[sheet].empty:
            out[sheet] = normalize_dates(out[sheet], cols)

    # 节假日：以维度表为准补齐
    for sheet in [config.SHEET_PURCHASE, config.SHEET_DAILY_SALES,
                  config.SHEET_TRAFFIC, config.SHEET_CONSUMPTION]:
        if sheet in out and not out[sheet].empty:
            out[sheet] = attach_holiday(out[sheet], dim)

    # 购买记录补充商品名称
    if config.SHEET_PURCHASE in out and config.SHEET_BOM in out:
        out[config.SHEET_PURCHASE] = enrich_purchases(
            out[config.SHEET_PURCHASE], out[config.SHEET_BOM]
        )

    # 原料采购：从"1月"文本解析月份数字
    if config.SHEET_PURCHASE_MONTHLY in out and not out[config.SHEET_PURCHASE_MONTHLY].empty:
        pm = out[config.SHEET_PURCHASE_MONTHLY].copy()
        pm["月份"] = pm["日期"].map(parse_month)
        out[config.SHEET_PURCHASE_MONTHLY] = pm

    return out
