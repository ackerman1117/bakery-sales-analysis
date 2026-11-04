"""数据清洗层：日期/时间解析、维度补全、BOM 单位换算、类型与键校验。"""

import datetime as dt
import re
from typing import Dict

import pandas as pd

from . import config


def to_date(value):
    """把混杂格式的日期值统一为 Timestamp。

    支持：datetime、20261201、'20261201'、'2026-12-01'、'2026/12/1'。
    """
    if pd.isna(value):
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value

    text = str(value).strip()
    digits = re.sub(r"\D", "", text)
    if text.replace(".0", "").isdigit() or digits == text:
        if len(digits) == 8:
            return pd.to_datetime(digits, format="%Y%m%d", errors="coerce")
        return pd.NaT  # 6 位（YYYYMM）等不完整日期
    return pd.to_datetime(text, errors="coerce")


def to_hour(value):
    """把时间值转为 0-23 的小时整数。"""
    if pd.isna(value):
        return pd.NA
    if isinstance(value, (dt.time, dt.datetime)):
        return value.hour
    if isinstance(value, pd.Timestamp):
        return value.hour

    text = str(value).strip()
    match = re.match(r"(\d{1,2}):(\d{1,2})", text)
    if match:
        hour = int(match.group(1))
        return hour if 0 <= hour <= 23 else pd.NA
    if text.isdigit() and len(text) in (3, 4, 5, 6):  # 91841 / 091841 之类
        text = text.zfill(6)
        hour = int(text[:2])
        return hour if 0 <= hour <= 23 else pd.NA
    return pd.NA


def _normalize_text(df: pd.DataFrame, columns) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].astype("string").str.strip().replace({"": pd.NA})
    return out


def normalize_date_dim(dim: pd.DataFrame) -> pd.DataFrame:
    """日期维度表标准化：日期转 Timestamp、去重、布尔/文本列规整。"""
    if dim.empty:
        return dim

    out = dim.copy()
    out["日期"] = out["日期"].map(to_date)
    out = out.dropna(subset=["日期"]).drop_duplicates(subset=["日期"])

    for col in ["是否节假日", "是否周末"]:
        if col in out.columns:
            out[col] = out[col].astype("string").str.strip().replace({"": "否"}).fillna("否")
    if "日期类型" not in out.columns:
        out["日期类型"] = out["是否节假日"].map(lambda x: "法定节假日" if x == "是" else "工作日")
    return out.sort_values("日期").reset_index(drop=True)


def normalize_purchases(df: pd.DataFrame) -> pd.DataFrame:
    """购买记录标准化：日期、小时、数值、文本、商品键。"""
    if df.empty:
        return df

    out = df.copy()
    out["日期"] = out["日期"].map(to_date)
    out["小时"] = out["时间"].map(to_hour) if "时间" in out.columns else pd.NA
    out["小时"] = pd.to_numeric(out["小时"], errors="coerce").astype("Int64")

    for col in ["数量", "消费金额"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out["商品编号"] = pd.to_numeric(out["产品"], errors="coerce").astype("Int64")
    out = _normalize_text(out, ["单号", "身份id"])
    out["身份id"] = pd.to_numeric(out["身份id"], errors="coerce").astype("Int64")

    out["单价"] = (out["消费金额"] / out["数量"].replace(0, pd.NA)).round(2)
    return out.reset_index(drop=True)


def infer_bom_unit(bom: pd.DataFrame, material: pd.DataFrame) -> pd.DataFrame:
    """为 BOM 每一行确定配方单位与基准单位。

    优先用 BOM 自带的「单位」列；没有时按原料形态推断：
    液体（原材料信息单位为 L/升/ml/毫升）用 ml，其余用 g。
    """
    out = bom.copy()
    out["重量"] = pd.to_numeric(out["重量"], errors="coerce")

    liquid_names = set()
    if not material.empty and {"原料名称", "单位"}.issubset(material.columns):
        unit_map = (material.assign(_u=material["单位"].astype("string").str.strip().str.lower())
                    .drop_duplicates("原料名称").set_index("原料名称")["_u"])
        liquid_names = {
            name for name, unit in unit_map.items()
            if isinstance(unit, str) and unit in config.LIQUID_UNITS
        }

    explicit_unit = (
        out["单位"].astype("string").str.strip().str.lower()
        if "单位" in out.columns else pd.Series(pd.NA, index=out.index, dtype="string")
    )

    def resolve_unit(name, unit):
        if isinstance(unit, str) and unit in config.UNIT_FACTORS:
            return unit
        return config.DEFAULT_LIQUID_UNIT if name in liquid_names else config.DEFAULT_SOLID_UNIT

    out["配方单位"] = [
        resolve_unit(name, unit)
        for name, unit in zip(out["原材料"], explicit_unit.tolist())
    ]
    base = out["配方单位"].map(lambda u: config.UNIT_FACTORS[u][0])
    factor = out["配方单位"].map(lambda u: config.UNIT_FACTORS[u][1])
    out["基准单位"] = base
    out["单件基准用量"] = (out["重量"] * factor).round(4)
    return out


def normalize_bom(bom: pd.DataFrame, material: pd.DataFrame) -> pd.DataFrame:
    """商品原料信息标准化，并补充口味名称与单件基准用量。"""
    if bom.empty:
        return bom

    out = bom.copy()
    out["商品编号"] = pd.to_numeric(out["商品编号"], errors="coerce").astype("Int64")
    out["口味风格"] = pd.to_numeric(out["口味风格"], errors="coerce").astype("Int64")
    out["口味"] = out["口味风格"].map(config.TASTE_MAP).fillna("未知")
    out = _normalize_text(out, ["商品名称", "原材料"])
    out = infer_bom_unit(out, material)
    return out.dropna(subset=["商品编号", "原材料"]).reset_index(drop=True)


def normalize_material(material: pd.DataFrame) -> pd.DataFrame:
    """原材料信息标准化：价格统一视为「元 / 基准单位（KG 或 L）」。"""
    if material.empty:
        return material

    out = material.copy()
    out = _normalize_text(out, ["原料名称", "规格", "单位"])
    for col in ["数量", "价格"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "单位" in out.columns:
        unit_map = {"l": "L", "升": "L", "ml": "L", "毫升": "L",
                    "g": "kg", "克": "kg", "kg": "kg", "千克": "kg"}
        out["单位"] = out["单位"].str.lower().map(unit_map).fillna(out["单位"])
    return out.dropna(subset=["原料名称"]).reset_index(drop=True)


def normalize_actual_consumption(df: pd.DataFrame) -> pd.DataFrame:
    """可选输入：原料实际消耗（日期 / 原料名称 / 消耗量 / 单位）。

    单位统一换算为基准单位（固体 kg、液体 L），便于和理论消耗直接对比。
    """
    if df.empty:
        return df

    out = df.copy()
    out["日期"] = out["日期"].map(to_date)
    out["消耗量"] = pd.to_numeric(out["消耗量"], errors="coerce")
    out = _normalize_text(out, ["原料名称", "单位"])
    if "单位" in out.columns:
        unit_map = {"l": "L", "升": "L", "ml": "L", "毫升": "L",
                    "g": "kg", "克": "kg", "kg": "kg", "千克": "kg"}
        out["单位"] = out["单位"].str.lower().map(unit_map).fillna(out["单位"])
    return out.dropna(subset=["日期", "原料名称", "消耗量"]).reset_index(drop=True)


def attach_date_dim(fact: pd.DataFrame, dim: pd.DataFrame) -> pd.DataFrame:
    """用日期维度表补全星期、日期类型、节假日等属性。"""
    if fact.empty or dim.empty or "日期" not in fact.columns:
        return fact

    keep = [c for c in ["日期", "年", "月", "星期", "日期类型", "是否节假日", "节假日名称"]
            if c in dim.columns]
    attributes = dim[keep].copy()
    if "是否节假日" in attributes.columns:
        attributes = attributes.rename(columns={"是否节假日": "节假日"})
    attributes = attributes.drop_duplicates(subset=["日期"])

    out = fact.drop(columns=[c for c in ["节假日"] if c in fact.columns], errors="ignore")
    return out.merge(attributes, on="日期", how="left")


def enrich_purchases(df: pd.DataFrame, bom: pd.DataFrame) -> pd.DataFrame:
    """为购买记录补充商品名称与口味（商品编号 → BOM 维度）。"""
    if df.empty or bom.empty:
        return df

    product = (bom.drop_duplicates("商品编号")
               [["商品编号", "商品名称", "口味风格", "口味"]] )
    return df.merge(product, on="商品编号", how="left")


def clean_all(frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """对输入表做统一清洗，返回新的 frames。"""
    out = dict(frames)
    dim = normalize_date_dim(frames.get(config.SHEET_DATE_DIM, pd.DataFrame()))
    material = normalize_material(frames.get(config.SHEET_MATERIAL, pd.DataFrame()))

    out[config.SHEET_DATE_DIM] = dim
    out[config.SHEET_MATERIAL] = material
    out[config.SHEET_BOM] = normalize_bom(frames.get(config.SHEET_BOM, pd.DataFrame()), material)

    purchases = normalize_purchases(frames.get(config.SHEET_PURCHASE, pd.DataFrame()))
    purchases = attach_date_dim(purchases, dim)
    out[config.SHEET_PURCHASE] = enrich_purchases(purchases, out[config.SHEET_BOM])

    out[config.SHEET_ACTUAL_CONSUMPTION] = normalize_actual_consumption(
        frames.get(config.SHEET_ACTUAL_CONSUMPTION, pd.DataFrame())
    )
    return out
