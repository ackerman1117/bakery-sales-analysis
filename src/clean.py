"""数据清洗层：日期/时间解析、维度补全、商品信息生成、BOM 单位换算与键校验。"""

import datetime as dt
import re
import unicodedata
from typing import Dict

import pandas as pd

from . import config
from .load import DataSchemaError


def canonical_product_name(value):
    """商品名称归一：全角/半角统一（NFKC）、去所有空白。

    保留中文/英文大小写原貌用于展示；匹配键另行转小写。
    """
    if pd.isna(value):
        return pd.NA
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", "", text)
    return text.strip() or pd.NA


def product_name_key(value):
    """商品名称匹配键：在 canonical_product_name 基础上去空白并转小写。"""
    name = canonical_product_name(value)
    return name.lower() if isinstance(name, str) else pd.NA


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
    """购买记录标准化：日期、小时、数值、文本、商品名称键。

    源表只有商品名称；商品编号/口味在生成「商品信息」后按名称 join 补回。
    """
    if df.empty:
        return df

    out = df.copy()
    out["日期"] = out["日期"].map(to_date)
    out["小时"] = out["时间"].map(to_hour) if "时间" in out.columns else pd.NA
    out["小时"] = pd.to_numeric(out["小时"], errors="coerce").astype("Int64")

    for col in ["数量", "消费金额"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out["_原始商品名称"] = out["商品名称"].astype("string")
    out["商品名称"] = out["商品名称"].map(canonical_product_name)
    out["名称键"] = out["商品名称"].map(product_name_key)
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
    """商品原料信息标准化：只依赖商品名称/原材料/重量，补充基准用量。"""
    if bom.empty:
        return bom

    out = bom.copy()
    out["_原始商品名称"] = out["商品名称"].astype("string")
    out["商品名称"] = out["商品名称"].map(canonical_product_name)
    out["名称键"] = out["商品名称"].map(product_name_key)
    out["原材料"] = out["原材料"].map(canonical_product_name)
    out = infer_bom_unit(out, material)
    return out.dropna(subset=["商品名称", "原材料", "重量"]).reset_index(drop=True)


def normalize_material(material: pd.DataFrame) -> pd.DataFrame:
    """原材料信息标准化：价格统一视为「元 / 基准单位（KG 或 L）」。"""
    if material.empty:
        return material

    out = material.copy()
    out["原料名称"] = out["原料名称"].map(canonical_product_name)
    out = _normalize_text(out, ["规格", "单位"])
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


def _infer_category(name: str) -> str:
    """按 config.CATEGORY_RULES 的关键字顺序推断商品类别。"""
    for keywords, category in config.CATEGORY_RULES:
        if any(keyword in name for keyword in keywords):
            return category
    return config.DEFAULT_CATEGORY


def _infer_taste(name: str, key: str) -> int:
    """口味推断：显式覆盖表 → 咸味关键词 → 默认甜味。"""
    overrides = {product_name_key(k): v for k, v in config.TASTE_OVERRIDES.items()}
    if key in overrides:
        return int(overrides[key])
    if any(keyword in name for keyword in config.TASTE_SAVORY_KEYWORDS):
        return 2
    return int(config.DEFAULT_TASTE)


def build_product_info(purchases: pd.DataFrame, bom: pd.DataFrame) -> pd.DataFrame:
    """生成商品信息：名称并集 → 稳定编号、口味、类别。

    编号规则：
    1) config.LEGACY_PRODUCT_IDS 中的商品固定为 1-5，兼容旧「产品生产」表；
    2) 其余商品按（类别优先级, 名称）排序后从 6 开始编号，跳过已占用编号。
    同一输入多次运行结果完全一致；新增商品会自动进入映射。
    """
    parts = []
    for df, source in ((bom, "BOM"), (purchases, "购买记录")):
        if df is None or df.empty or "名称键" not in df.columns:
            continue
        part = df[["名称键", "商品名称"]].dropna().copy()
        part["来源"] = source
        parts.append(part)

    columns = ["商品编号", "商品名称", "口味风格", "口味", "商品类别", "名称键"]
    if not parts:
        return pd.DataFrame(columns=columns)

    names = pd.concat(parts, ignore_index=True)
    names["_来源优先级"] = names["来源"].map({"BOM": 0, "购买记录": 1})
    names = names.sort_values(["名称键", "_来源优先级", "商品名称"], kind="mergesort")
    display = names.drop_duplicates("名称键").set_index("名称键")["商品名称"]

    legacy = {product_name_key(name): int(pid)
              for name, pid in config.LEGACY_PRODUCT_IDS.items()}
    category = {key: _infer_category(str(name)) for key, name in display.items()}
    taste = {key: _infer_taste(str(name), key) for key, name in display.items()}
    category_rank = {name: i for i, name in enumerate(config.CATEGORY_ORDER)}

    ids = {}
    used = set(int(v) for v in config.LEGACY_PRODUCT_IDS.values())
    for key in display.index:
        if key in legacy:
            ids[key] = legacy[key]
    remaining = [key for key in display.index if key not in legacy]
    remaining.sort(key=lambda k: (category_rank.get(category[k], len(category_rank)),
                                  display[k]))
    next_id = 1
    for key in remaining:
        while next_id in used:
            next_id += 1
        ids[key] = next_id
        used.add(next_id)
        next_id += 1

    info = pd.DataFrame({
        "商品编号": [ids[key] for key in display.index],
        "商品名称": [display[key] for key in display.index],
        "口味风格": [taste[key] for key in display.index],
        "口味": [config.TASTE_MAP.get(taste[key], "未知") for key in display.index],
        "商品类别": [category[key] for key in display.index],
        "名称键": list(display.index),
    }, columns=columns)
    return info.sort_values("商品编号").reset_index(drop=True)


def build_name_audit(purchases: pd.DataFrame, bom: pd.DataFrame) -> pd.DataFrame:
    """记录归一前后的名称，用于发现“不同写法归一成同一商品”的歧义。"""
    parts = []
    for df, source in ((bom, "BOM"), (purchases, "购买记录")):
        if df is None or df.empty or "_原始商品名称" not in df.columns:
            continue
        part = df[["名称键", "_原始商品名称"]].dropna().rename(
            columns={"_原始商品名称": "商品名称"})
        part["来源"] = source
        parts.append(part)
    if not parts:
        return pd.DataFrame(columns=["名称键", "商品名称", "来源"])
    return (pd.concat(parts, ignore_index=True)
            .drop_duplicates()
            .sort_values(["名称键", "商品名称", "来源"], kind="mergesort")
            .reset_index(drop=True))


def apply_product_info(df: pd.DataFrame, product_info: pd.DataFrame,
                       table_name: str) -> pd.DataFrame:
    """按名称键把商品编号/口味/类别 join 回业务表。

    查不到映射时给出缺失商品名，并提示应该在哪张表补名称。
    """
    if df.empty:
        return df

    blank_rows = int(df["商品名称"].isna().sum())
    if blank_rows:
        raise DataSchemaError(
            f"「{table_name}」有 {blank_rows} 行商品名称为空。请在「{config.SHEET_BOM}」"
            f"或「{config.SHEET_PURCHASE}」中补全商品名称后再运行。"
        )

    mapping = product_info[["名称键", "商品编号", "商品名称", "口味风格", "口味", "商品类别"]]
    missing_keys = sorted(set(df["名称键"].dropna()) - set(mapping["名称键"]))
    if missing_keys:
        missing_names = sorted(
            set(df.loc[df["名称键"].isin(missing_keys), "商品名称"].dropna().astype(str))
        )
        raise DataSchemaError(
            f"「{table_name}」有 {len(missing_names)} 个商品名称无法在运行时「商品信息」中查到："
            f"{'、'.join(missing_names)}。请检查名称是否写错；新增商品请在"
            f"「{config.SHEET_BOM}」中补充该商品名称的同名原料配方。"
        )

    out = df.drop(columns=["商品名称"], errors="ignore").merge(
        mapping, on="名称键", how="left"
    )
    return out


def clean_all(frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """对输入表做统一清洗，返回新的 frames（含运行时商品信息）。"""
    out = dict(frames)
    dim = normalize_date_dim(frames.get(config.SHEET_DATE_DIM, pd.DataFrame()))
    material = normalize_material(frames.get(config.SHEET_MATERIAL, pd.DataFrame()))
    bom = normalize_bom(frames.get(config.SHEET_BOM, pd.DataFrame()), material)
    purchases = normalize_purchases(frames.get(config.SHEET_PURCHASE, pd.DataFrame()))

    # 先由「购买记录 + BOM」生成商品信息，再按名称回填编号/口味/类别。
    product_info = build_product_info(purchases, bom)
    name_audit = build_name_audit(purchases, bom)
    purchases = apply_product_info(purchases, product_info, config.SHEET_PURCHASE)
    bom = apply_product_info(bom, product_info, config.SHEET_BOM)
    purchases = attach_date_dim(purchases, dim)

    out[config.SHEET_DATE_DIM] = dim
    out[config.SHEET_MATERIAL] = material
    out[config.SHEET_BOM] = bom.drop(columns=["_原始商品名称"], errors="ignore")
    out[config.SHEET_PURCHASE] = purchases.drop(columns=["_原始商品名称"], errors="ignore")
    out[config.SHEET_PRODUCT_INFO] = product_info
    out["_名称审计"] = name_audit
    out[config.SHEET_ACTUAL_CONSUMPTION] = normalize_actual_consumption(
        frames.get(config.SHEET_ACTUAL_CONSUMPTION, pd.DataFrame())
    )
    return out
