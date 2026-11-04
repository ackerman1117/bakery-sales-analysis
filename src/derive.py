"""派生层：全部由「购买记录 + 商品原料信息 + 日期维度表」计算得到。

这里只产出最基础的事实结果（单日销量、分时段客流、偏好、理论原料消耗），
后续的排班、采购建议、实际消耗对比等经营分析放在 analysis.py。
"""

import numpy as np
import pandas as pd

DATE_ATTRS = ["年", "月", "星期", "日期类型", "节假日", "节假日名称"]


def valid_purchases(purchases: pd.DataFrame) -> pd.DataFrame:
    """只保留可用于计算的明细：有日期、商品编号、正数量。"""
    if purchases.empty:
        return purchases

    df = purchases.copy()
    if "日期" not in df.columns:
        return pd.DataFrame()
    df = df.dropna(subset=["日期", "商品编号", "数量"])
    df = df[df["数量"] > 0]
    df["_顾客"] = _customer_key(df)
    return df.reset_index(drop=True)


def _customer_key(df: pd.DataFrame) -> pd.Series:
    """顾客标识：优先身份id，缺失时退化为单号，保证人次不为空。"""
    if "身份id" in df.columns:
        key = df["身份id"].astype("string")
        if "单号" in df.columns:
            key = key.fillna(df["单号"].astype("string"))
        return key
    if "单号" in df.columns:
        return df["单号"].astype("string")
    return pd.Series(pd.NA, index=df.index, dtype="string")


def present_columns(df: pd.DataFrame, columns) -> list:
    return [c for c in columns if c in df.columns]


def daily_product_sales(purchases: pd.DataFrame) -> pd.DataFrame:
    """单日产品销售量：日期 × 商品。

    销量 = Σ数量，销售额 = Σ消费金额，订单数 = 去重单号，
    购买人次 = 去重身份id（缺失时按单号计），平均单价 = 销售额 / 销量。
    """
    df = valid_purchases(purchases)
    if df.empty:
        return pd.DataFrame()

    keys = present_columns(df, ["日期"] + DATE_ATTRS + ["商品编号", "商品名称", "口味"])
    grouped = (df.groupby(keys, dropna=False, as_index=False)
               .agg(销量=("数量", "sum"), 销售额=("消费金额", "sum"),
                    订单数=("单号", "nunique"), 购买人次=("_顾客", "nunique")))
    grouped["平均单价"] = (grouped["销售额"] / grouped["销量"].replace(0, pd.NA)).round(2)
    grouped["销售额"] = grouped["销售额"].round(2)
    return grouped.sort_values(["日期", "商品编号"]).reset_index(drop=True)


def hourly_traffic(purchases: pd.DataFrame) -> pd.DataFrame:
    """客流量（分时段）：日期 × 小时。"""
    df = valid_purchases(purchases)
    if df.empty or "小时" not in df.columns:
        return pd.DataFrame()
    df = df.dropna(subset=["小时"])
    if df.empty:
        return pd.DataFrame()

    df = df.assign(小时=df["小时"].astype(int),
                   时段=df["小时"].map(lambda h: f"{h:02d}:00-{h + 1:02d}:00"))
    keys = present_columns(df, ["日期"] + DATE_ATTRS + ["小时", "时段"])
    res = (df.groupby(keys, dropna=False, as_index=False)
           .agg(消费人次=("_顾客", "nunique"), 订单数=("单号", "nunique"),
                销量=("数量", "sum"), 销售额=("消费金额", "sum")))
    res["客单价"] = (res["销售额"] / res["订单数"].replace(0, pd.NA)).round(2)
    res["人均消费"] = (res["销售额"] / res["消费人次"].replace(0, pd.NA)).round(2)
    res["销售额"] = res["销售额"].round(2)
    return res.sort_values(["日期", "小时"]).reset_index(drop=True)


def product_preference(purchases: pd.DataFrame, daily_sales: pd.DataFrame) -> pd.DataFrame:
    """产品偏好：商品粒度汇总销量、销售额、复购与排名。"""
    if daily_sales.empty:
        return pd.DataFrame()

    base = (daily_sales.groupby(["商品编号", "商品名称", "口味"], dropna=False, as_index=False)
            .agg(历史总销量=("销量", "sum"), 历史总销售额=("销售额", "sum"),
                 有销售天数=("日期", "nunique")))
    base["平均单价"] = (base["历史总销售额"] / base["历史总销量"].replace(0, pd.NA)).round(2)
    base["日均销量"] = (base["历史总销量"] / base["有销售天数"]).round(2)
    base["日均销售额"] = (base["历史总销售额"] / base["有销售天数"]).round(2)

    orders = _product_order_stats(valid_purchases(purchases))
    res = base.merge(orders, on="商品编号", how="left")

    total_qty = res["历史总销量"].sum()
    total_amt = res["历史总销售额"].sum()
    res["销量占比"] = (res["历史总销量"] / total_qty).round(4) if total_qty else np.nan
    res["销售额占比"] = (res["历史总销售额"] / total_amt).round(4) if total_amt else np.nan
    res["销量排名"] = res["历史总销量"].rank(ascending=False, method="min").astype(int)
    res["销售额排名"] = res["历史总销售额"].rank(ascending=False, method="min").astype(int)

    res = res[["商品编号", "商品名称", "口味", "历史总销量", "历史总销售额",
               "销量占比", "销售额占比", "购买订单数", "购买人次", "复购人次", "复购率",
               "有销售天数", "日均销量", "日均销售额", "平均单价", "销量排名", "销售额排名"]]
    return res.sort_values("历史总销量", ascending=False).reset_index(drop=True)


def _product_order_stats(df: pd.DataFrame) -> pd.DataFrame:
    """商品维度的订单数、购买人次、复购人次。"""
    if df.empty:
        return pd.DataFrame(columns=["商品编号", "购买订单数", "购买人次", "复购人次", "复购率"])

    agg = (df.groupby("商品编号", as_index=False)
           .agg(购买订单数=("单号", "nunique"), 购买人次=("_顾客", "nunique")))

    per_customer = (df.groupby(["商品编号", "_顾客"], dropna=False)["单号"]
                    .nunique().rename("订单次数").reset_index())
    repeat = (per_customer.assign(是否复购=per_customer["订单次数"] > 1)
              .groupby("商品编号", as_index=False)["是否复购"].sum()
              .rename(columns={"是否复购": "复购人次"}))
    repeat["复购人次"] = repeat["复购人次"].astype(int)

    res = agg.merge(repeat, on="商品编号", how="left")
    res["复购人次"] = res["复购人次"].fillna(0).astype(int)
    res["复购率"] = (res["复购人次"] / res["购买人次"].replace(0, pd.NA)).round(4)
    return res


def taste_preference(purchases: pd.DataFrame) -> pd.DataFrame:
    """口味偏好：口味粒度汇总销量、销售额、占比与日均。"""
    df = valid_purchases(purchases)
    if df.empty or "口味" not in df.columns:
        return pd.DataFrame()

    keys = present_columns(df, ["口味风格", "口味"])
    res = (df.groupby(keys, dropna=False, as_index=False)
           .agg(历史总销量=("数量", "sum"), 历史总销售额=("消费金额", "sum"),
                购买订单数=("单号", "nunique"), 购买人次=("_顾客", "nunique"),
                有销售天数=("日期", "nunique")))
    res["日均销量"] = (res["历史总销量"] / res["有销售天数"]).round(2)
    res["日均销售额"] = (res["历史总销售额"] / res["有销售天数"]).round(2)
    res["销量占比"] = (res["历史总销量"] / res["历史总销量"].sum()).round(4)
    res["销售额占比"] = (res["历史总销售额"] / res["历史总销售额"].sum()).round(4)
    res = res.rename(columns={"口味风格": "口味编码"})
    return res.sort_values("历史总销量", ascending=False).reset_index(drop=True)


def material_consumption_daily(purchases: pd.DataFrame,
                               bom: pd.DataFrame,
                               sales_daily: pd.DataFrame = None) -> pd.DataFrame:
    """原料理论消耗：单日销量 × BOM 单件用量。

    消耗量统一按 BOM 换算后的基准单位（固体 kg、液体 L）。
    """
    if bom.empty:
        return pd.DataFrame()
    if sales_daily is None:
        sales_daily = daily_product_sales(purchases)
    if sales_daily.empty:
        return pd.DataFrame()

    cols = present_columns(sales_daily, ["日期"] + DATE_ATTRS + ["商品编号", "销量"])
    bom_cols = ["商品编号", "原材料", "基准单位", "单件基准用量"]
    detail = sales_daily[cols].merge(bom[bom_cols], on="商品编号", how="inner")
    if detail.empty:
        return pd.DataFrame()

    detail["理论消耗量"] = detail["销量"] * detail["单件基准用量"]
    keys = present_columns(detail, ["日期"] + DATE_ATTRS + ["原材料", "基准单位"])
    res = (detail.groupby(keys, dropna=False, as_index=False)
           .agg(理论消耗量=("理论消耗量", "sum"), 关联商品销量=("销量", "sum")))
    res = res.rename(columns={"原材料": "原料名称", "基准单位": "计量单位"})
    res["理论消耗量"] = res["理论消耗量"].round(3)
    return res.sort_values(["日期", "原料名称"]).reset_index(drop=True)
