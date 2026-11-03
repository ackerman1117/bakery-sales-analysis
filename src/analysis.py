"""分析层：每个函数输入清洗后的 DataFrame，返回结果 DataFrame。"""

import pandas as pd

from . import config


# ---------------- 销售概览 ----------------
def sales_kpis(purchases: pd.DataFrame, daily_sales: pd.DataFrame) -> pd.DataFrame:
    """核心经营指标。

    优先用「单日产品销售量」汇总（口径完整），缺失时回退到「购买记录」。
    """
    rows = []
    if not purchases.empty:
        rows.append(("订单数", f"{purchases['单号'].nunique():,}"))
        rows.append(("明细行数", f"{len(purchases):,}"))
        rows.append(("购买记录总销售额（元）", f"{purchases['消费金额'].sum():,.2f}"))
        if purchases["数量"].sum():
            rows.append(("购买记录总销量（件）", f"{int(purchases['数量'].sum()):,}"))
        avg_ticket = purchases.groupby("单号")["消费金额"].sum().mean()
        rows.append(("客单价（元/单）", f"{avg_ticket:.2f}"))

    if not daily_sales.empty:
        total_qty = int(daily_sales["销量"].sum())
        has_amt = "销售额" in daily_sales.columns
        total_amt = float(daily_sales["销售额"].sum()) if has_amt else None
        days = daily_sales["日期"].nunique()
        rows.append(("统计天数", f"{days}"))
        rows.append(("总销量（件）", f"{total_qty:,}"))
        if total_amt is not None:
            rows.append(("总销售额（元）", f"{total_amt:,.2f}"))
        rows.append(("日均销量（件/天）", f"{total_qty / days:,.1f}"))
        if total_amt is not None:
            rows.append(("日均销售额（元/天）", f"{total_amt / days:,.2f}"))

    return pd.DataFrame(rows, columns=["指标", "数值"])


# ---------------- 产品排名 ----------------
def product_ranking(daily_sales: pd.DataFrame) -> pd.DataFrame:
    """产品销量/销售额排名与占比。"""
    if daily_sales.empty:
        return pd.DataFrame()

    amount_col = "销售额" if "销售额" in daily_sales.columns else None
    agg = {"销量": "sum"}
    if amount_col:
        agg[amount_col] = "sum"

    res = daily_sales.groupby(["商品编号", "商品名称"], as_index=False).agg(agg)
    res = res.rename(columns={"销量": "总销量"})
    if amount_col:
        res = res.rename(columns={amount_col: "总销售额"})
        res["销售额占比"] = (res["总销售额"] / res["总销售额"].sum()).round(4)
    res["销量占比"] = (res["总销量"] / res["总销量"].sum()).round(4)
    res["排名"] = res["总销量"].rank(ascending=False, method="min").astype(int)
    return res.sort_values("总销量", ascending=False).reset_index(drop=True)


# ---------------- 口味偏好 ----------------
def taste_ranking(daily_sales: pd.DataFrame,
                  bom: pd.DataFrame) -> pd.DataFrame:
    """按口味编码聚合销量与销售额。"""
    if daily_sales.empty or bom.empty:
        return pd.DataFrame()

    taste = (bom.drop_duplicates("商品编号")[["商品编号", "口味风格"]]
             .copy())
    taste["口味"] = taste["口味风格"].map(config.TASTE_MAP).fillna("未知")

    df = daily_sales.merge(taste[["商品编号", "口味"]], on="商品编号", how="left")
    agg = {"销量": "sum"}
    if "销售额" in df.columns:
        agg["销售额"] = "sum"
    res = df.groupby("口味", as_index=False).agg(agg)
    res = res.rename(columns={"销量": "总销量", "销售额": "总销售额"})
    res["销量占比"] = (res["总销量"] / res["总销量"].sum()).round(4)
    if "总销售额" in res.columns:
        res["销售额占比"] = (res["总销售额"] / res["总销售额"].sum()).round(4)
    return res.sort_values("总销量", ascending=False).reset_index(drop=True)


# ---------------- 节假日效应 ----------------
def holiday_effect(daily_sales: pd.DataFrame) -> pd.DataFrame:
    """节假日 vs 非节假日 的日均销量/销售额对比。"""
    if daily_sales.empty or "节假日" not in daily_sales.columns:
        return pd.DataFrame()

    daily = daily_sales.groupby(["日期", "节假日"], as_index=False).agg(
        {"销量": "sum", **({"销售额": "sum"} if "销售额" in daily_sales.columns else {})}
    )
    res = daily.groupby("节假日", as_index=False).agg(
        {"销量": "mean", **({"销售额": "mean"} if "销售额" in daily.columns else {}), "日期": "nunique"}
    )
    res = res.rename(columns={
        "节假日": "类型", "销量": "日均销量", "销售额": "日均销售额", "日期": "天数"
    })
    res["日均销量"] = res["日均销量"].round(1)
    if "日均销售额" in res.columns:
        res["日均销售额"] = res["日均销售额"].round(2)
    return res


# ---------------- 生产与销售匹配 ----------------
def production_vs_sales(production: pd.DataFrame,
                        daily_sales: pd.DataFrame) -> pd.DataFrame:
    """同一商品同一天：产量 vs 销量，差值即剩余/缺口。"""
    if production.empty or daily_sales.empty:
        return pd.DataFrame()

    prod = production.groupby(["商品编号", "商品名称", "日期"], as_index=False)["数量"].sum()
    prod = prod.rename(columns={"数量": "产量"})
    sales = daily_sales.groupby(["商品编号", "日期"], as_index=False)["销量"].sum()

    res = prod.merge(sales, on=["商品编号", "日期"], how="outer")
    res["产量"] = res["产量"].fillna(0).astype(int)
    res["销量"] = res["销量"].fillna(0).astype(int)
    res["差值"] = res["产量"] - res["销量"]
    res["售罄率"] = (res["销量"] / res["产量"].replace(0, pd.NA)).round(4)
    return res.sort_values(["日期", "商品编号"]).reset_index(drop=True)


# ---------------- 原料消耗 ----------------
def material_consumption(consumption: pd.DataFrame,
                         material: pd.DataFrame = None) -> pd.DataFrame:
    """各原料总消耗与日均消耗。"""
    if consumption.empty:
        return pd.DataFrame()

    res = (consumption.groupby("原料名称", as_index=False)
           .agg(总消耗量=("消耗量", "sum"), 日均消耗量=("消耗量", "mean")))
    res["总消耗量"] = res["总消耗量"].round(1)
    res["日均消耗量"] = res["日均消耗量"].round(2)
    res = res.sort_values("总消耗量", ascending=False).reset_index(drop=True)

    if material is not None and not material.empty and "价格" in material.columns:
        res = res.merge(material[["原料名称", "价格"]], on="原料名称", how="left")
        res["消耗成本估算"] = (res["总消耗量"] * res["价格"]).round(2)
    return res


# ---------------- 采购 vs 消耗 ----------------
def purchase_vs_consumption(purchase_monthly: pd.DataFrame,
                            consumption: pd.DataFrame) -> pd.DataFrame:
    """按月对比采购量与消耗量（仅对两者都存在的原料）。"""
    if purchase_monthly.empty or consumption.empty:
        return pd.DataFrame()

    pm = purchase_monthly.copy()
    pm = pm[pm["月份"].notna()]
    buy = pm.groupby(["原料名称", "月份"], as_index=False)["数量"].sum()
    buy = buy.rename(columns={"数量": "采购量"})

    cons = consumption.copy()
    cons["月份"] = cons["日期"].dt.month
    use = cons.groupby(["原料名称", "月份"], as_index=False)["消耗量"].sum()

    res = buy.merge(use, on=["原料名称", "月份"], how="outer")
    res["采购量"] = res["采购量"].fillna(0).round(1)
    res["消耗量"] = res["消耗量"].fillna(0).round(1)
    res["差值"] = (res["采购量"] - res["消耗量"]).round(1)
    return res.sort_values(["原料名称", "月份"]).reset_index(drop=True)


# ---------------- 客流 ----------------
def traffic_analysis(traffic: pd.DataFrame) -> pd.DataFrame:
    """分时段客流：人次、销售额、客单价。"""
    if traffic.empty:
        return pd.DataFrame()

    res = traffic.groupby("时间段（每小时）", as_index=False).agg(
        {"消费人次": "sum", "销售额": "sum"}
    )
    res["客单价"] = (res["销售额"] / res["消费人次"].replace(0, pd.NA)).round(2)
    total = res["消费人次"].sum()
    res["人次占比"] = (res["消费人次"] / total).round(4) if total else 0
    return res.sort_values("消费人次", ascending=False).reset_index(drop=True)


def traffic_peak(traffic: pd.DataFrame) -> pd.DataFrame:
    """高峰时段：人次最多的时段。"""
    res = traffic_analysis(traffic)
    if res.empty:
        return res
    return res.head(3)


# ---------------- 结果表一致性校验 ----------------
def check_result_tables(daily_sales: pd.DataFrame,
                        taste_pref: pd.DataFrame,
                        product_pref: pd.DataFrame) -> pd.DataFrame:
    """用明细重算，与「口味偏好」「产品偏好」结果表核对口径。"""
    checks = []

    if not daily_sales.empty and not product_pref.empty and "历史销售总量" in product_pref.columns:
        calc = daily_sales.groupby("商品名称")["销量"].sum()
        given = product_pref.set_index("产品名称")["历史销售总量"]
        common = calc.index.intersection(given.index)
        if len(common):
            diff = (calc[common] - given[common]).abs().max()
            checks.append(("产品偏好-历史销售总量", f"最大差异 {diff:.0f}", "通过" if diff == 0 else "不一致"))

    if not daily_sales.empty and not taste_pref.empty and "历史总销售量" in taste_pref.columns:
        t = taste_pref[taste_pref["日期类型"] == "年"]
        checks.append(("口味偏好-记录数", f"{len(t)} 条", "通过" if len(t) > 0 else "空表"))

    return pd.DataFrame(checks, columns=["校验项", "结果", "状态"])
