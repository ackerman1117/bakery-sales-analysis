"""经营分析层：KPI、节假日效应、客流规律、小时工排班、原料消耗与采购建议。"""

import calendar
import math

import numpy as np
import pandas as pd

from . import config, derive

WEEKDAY_ORDER = ["一", "二", "三", "四", "五", "六", "日"]


# ---------------- 基础日汇总 ----------------
def daily_summary(purchases: pd.DataFrame) -> pd.DataFrame:
    """按日汇总销量、销售额、订单数、消费人次。"""
    df = derive.valid_purchases(purchases)
    if df.empty:
        return pd.DataFrame()

    keys = derive.present_columns(df, ["日期"] + derive.DATE_ATTRS)
    res = (df.groupby(keys, dropna=False, as_index=False)
           .agg(销量=("数量", "sum"), 销售额=("消费金额", "sum"),
                订单数=("单号", "nunique"), 消费人次=("_顾客", "nunique")))
    res["销售额"] = res["销售额"].round(2)
    return res.sort_values("日期").reset_index(drop=True)


# ---------------- 销售概览 ----------------
def sales_kpis(purchases: pd.DataFrame, daily_sales: pd.DataFrame) -> pd.DataFrame:
    """核心经营指标，全部由购买记录派生。"""
    df = derive.valid_purchases(purchases)
    if df.empty:
        return pd.DataFrame(columns=["指标", "数值"])

    days = df["日期"].nunique()
    orders = df["单号"].nunique()
    customers = df["身份id"].nunique()
    total_qty = df["数量"].sum()
    total_amt = df["消费金额"].sum()

    rows = [
        ("数据区间", f"{df['日期'].min():%Y-%m-%d} ~ {df['日期'].max():%Y-%m-%d}"),
        ("营业天数", f"{days}"),
        ("订单数", f"{orders:,}"),
        ("顾客数（去重身份id）", f"{customers:,}"),
        ("总销量（件）", f"{total_qty:,.0f}"),
        ("总销售额（元）", f"{total_amt:,.2f}"),
        ("客单价（元/单）", f"{total_amt / orders:,.2f}" if orders else "-"),
        ("人均消费（元/人）", f"{total_amt / customers:,.2f}" if customers else "-"),
        ("日均销量（件/天）", f"{total_qty / days:,.1f}" if days else "-"),
        ("日均销售额（元/天）", f"{total_amt / days:,.2f}" if days else "-"),
        ("日均订单数（单/天）", f"{orders / days:,.1f}" if days else "-"),
        ("平均每单件数", f"{total_qty / orders:,.1f}" if orders else "-"),
    ]
    if not daily_sales.empty:
        rows.append(("有销售的商品数", f"{daily_sales['商品编号'].nunique()}"))

    return pd.DataFrame(rows, columns=["指标", "数值"])


# ---------------- 节假日效应 ----------------
def holiday_effect(daily: pd.DataFrame) -> pd.DataFrame:
    """按日期类型（工作日/周末/法定节假日/调休上班）对比日均表现。"""
    if daily.empty or "日期类型" not in daily.columns:
        return pd.DataFrame()

    agg_cols = {"日期": "nunique", "销量": "mean", "销售额": "mean",
                "订单数": "mean", "消费人次": "mean"}
    res = (daily.groupby("日期类型", as_index=False)
           .agg(agg_cols)
           .rename(columns={"日期类型": "日期类型", "日期": "天数", "销量": "日均销量",
                            "销售额": "日均销售额", "订单数": "日均订单数",
                            "消费人次": "日均消费人次"}))
    for col in ["日均销量", "日均销售额", "日均订单数", "日均消费人次"]:
        res[col] = res[col].round(2)

    base = res.loc[res["日期类型"] == "工作日", "日均销量"]
    if len(base):
        base_value = float(base.iloc[0])
        res["销量较工作日"] = (res["日均销量"] / base_value - 1).round(4) if base_value else np.nan
    return res.sort_values("天数", ascending=False).reset_index(drop=True)


# ---------------- 客流规律（分星期 × 小时） ----------------
def traffic_pattern(hourly: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """把一个星期内的小时段客流做平均，作为排班依据。"""
    if hourly.empty or daily.empty or "星期" not in hourly.columns:
        return pd.DataFrame()

    days = (daily.dropna(subset=["星期"])
            .groupby("星期", as_index=False)
            .agg(营业天数=("日期", "nunique")))
    hours = sorted(hourly["小时"].dropna().astype(int).unique())
    if not hours:
        return pd.DataFrame()

    weekdays = [w for w in WEEKDAY_ORDER if w in set(days["星期"])]
    # 营业时段按数据中出现的最早/最晚小时展开成完整网格，空白小时按 0 客流补足
    full_hours = list(range(min(hours), max(hours) + 1))
    grid = pd.MultiIndex.from_product([weekdays, full_hours], names=["星期", "小时"]).to_frame(index=False)
    grid["时段"] = grid["小时"].map(lambda h: f"{h:02d}:00-{h + 1:02d}:00")
    grid = grid.merge(days, on="星期", how="left")

    totals = (hourly.groupby(["星期", "小时"], as_index=False)
              .agg(消费人次=("消费人次", "sum"), 订单数=("订单数", "sum"),
                   销量=("销量", "sum"), 销售额=("销售额", "sum")))
    res = grid.merge(totals, on=["星期", "小时"], how="left").fillna(
        {"消费人次": 0, "订单数": 0, "销量": 0, "销售额": 0}
    )

    for src, dst in [("消费人次", "日均消费人次"), ("订单数", "日均订单数"),
                     ("销量", "日均销量"), ("销售额", "日均销售额")]:
        res[dst] = (res[src] / res["营业天数"].replace(0, pd.NA)).round(2)

    total = res["日均消费人次"].sum()
    res["客流占比"] = (res["日均消费人次"] / total).round(4) if total else np.nan
    keep = ["星期", "小时", "时段", "营业天数", "日均消费人次", "日均订单数",
            "日均销量", "日均销售额", "客流占比"]
    return res[keep]


# ---------------- 小时工排班建议 ----------------
def staffing_plan(pattern: pd.DataFrame) -> pd.DataFrame:
    """按「日均客流 ÷ 每人每小时服务能力」给出每个星期几、每个小时的在岗人数。"""
    if pattern.empty:
        return pd.DataFrame()

    res = pattern.copy()
    capacity = config.SERVICE_CAPACITY_PER_HOUR
    res["建议在岗人数"] = [
        int(math.ceil(v / capacity)) if v > 0 else 0
        for v in res["日均消费人次"].fillna(0)
    ]
    res["建议工时(小时/日)"] = res["建议在岗人数"] * 1

    if config.HOURLY_WAGE is not None:
        res["人力成本估算(元/日)"] = (res["建议在岗人数"] * config.HOURLY_WAGE).round(2)

    peak = res.loc[res["日均消费人次"] > 0, "日均消费人次"]
    threshold = float(peak.quantile(0.75)) if len(peak) else 0
    res["排班提示"] = np.where(
        res["日均消费人次"] >= threshold,
        f"高峰时段（{config.SERVICE_CAPACITY_PER_HOUR} 人次/人·小时）",
        np.where(res["建议在岗人数"] > 0, "常规时段", "无需在岗"),
    )
    keep = ["星期", "小时", "时段", "日均消费人次", "日均订单数", "建议在岗人数",
            "建议工时(小时/日)"]
    if "人力成本估算(元/日)" in res.columns:
        keep.append("人力成本估算(元/日)")
    keep.append("排班提示")
    return res[keep]


def _material_columns(material: pd.DataFrame) -> pd.DataFrame:
    """按需从原材料信息取列，缺列时补空，避免可选维度导致 KeyError。"""
    wanted = {
        "原料名称": None, "价格": np.nan, "单位": pd.NA,
        "规格": pd.NA, "数量": np.nan,
    }
    out = pd.DataFrame({"原料名称": material["原料名称"]})
    for col, default in list(wanted.items())[1:]:
        out[col] = material[col] if col in material.columns else default
    return out


# ---------------- 原料理论消耗汇总 ----------------
def material_summary(consumption_daily: pd.DataFrame,
                     material: pd.DataFrame,
                     actual: pd.DataFrame = None,
                     observed_days: int = None) -> pd.DataFrame:
    """原料维度的理论消耗、成本与（可选）实际消耗对比。"""
    if consumption_daily.empty:
        return pd.DataFrame()

    days = observed_days or consumption_daily["日期"].nunique()
    res = (consumption_daily.groupby(["原料名称", "计量单位"], as_index=False)
           .agg(理论总消耗量=("理论消耗量", "sum"), 有消耗天数=("日期", "nunique")))
    res["日均消耗量"] = (res["理论总消耗量"] / max(days, 1)).round(3)

    unit_total = res.groupby("计量单位")["理论总消耗量"].transform("sum")
    res["消耗量占比"] = (res["理论总消耗量"] / unit_total.replace(0, pd.NA)).round(4)

    if material is not None and not material.empty and "价格" in material.columns:
        mat = _material_columns(material).rename(
            columns={"单位": "原料单位", "规格": "包装规格", "数量": "单包装含量"}
        )
        res = res.merge(mat, on="原料名称", how="left")
        same_unit = res["原料单位"].isna() | (res["原料单位"] == res["计量单位"])
        res["单价"] = np.where(same_unit, res["价格"], np.nan)
        res["消耗成本估算"] = (res["理论总消耗量"] * res["单价"]).round(2)

    if actual is not None and not actual.empty:
        act = actual.groupby("原料名称", as_index=False)["消耗量"].sum()
        act = act.rename(columns={"消耗量": "实际总消耗量"})
        res = res.merge(act, on="原料名称", how="left")

        # 只有录入了实际消耗的「日期 × 原料」才拿来做同期对比，
        # 避免把只录了几天实际值的总量与整段理论总量直接相减。
        pairs = (actual.groupby(["日期", "原料名称"], as_index=False)["消耗量"].sum())
        theory_same = pairs.merge(
            consumption_daily[["日期", "原料名称", "理论消耗量"]],
            on=["日期", "原料名称"], how="left",
        )
        comparable = (theory_same.groupby("原料名称")["理论消耗量"].sum()
                      .rename("同期理论消耗量").reset_index())
        res = res.merge(comparable, on="原料名称", how="left")

        res["差异量"] = (res["实际总消耗量"] - res["同期理论消耗量"]).round(3)
        res["差异率"] = (res["差异量"] / res["同期理论消耗量"].replace(0, pd.NA)).round(4)
        res["消耗判定"] = _diff_label(res["差异率"])

    res["理论总消耗量"] = res["理论总消耗量"].round(3)
    cols = ["原料名称", "计量单位", "理论总消耗量", "日均消耗量", "有消耗天数", "消耗量占比"]
    if "单价" in res.columns:
        cols += ["单价", "消耗成本估算"]
    if actual is not None and not actual.empty:
        cols += ["实际总消耗量", "同期理论消耗量", "差异量", "差异率", "消耗判定"]
    res = res[cols]
    return res.sort_values(["计量单位", "理论总消耗量"], ascending=[True, False]).reset_index(drop=True)


def _diff_label(rate: pd.Series) -> pd.Series:
    if rate.isna().all():
        return pd.Series("未记录实际消耗", index=rate.index)
    return pd.Series(
        np.where(rate.isna(), "未记录实际消耗",
                 np.where(rate > 0.05, "超耗", np.where(rate < -0.05, "节省/可能漏记", "正常"))),
        index=rate.index,
    )


# ---------------- 实际 vs 理论（按日） ----------------
def actual_vs_theoretical(consumption_daily: pd.DataFrame,
                          actual: pd.DataFrame) -> pd.DataFrame:
    """按日期 × 原料对比实际消耗与理论消耗。"""
    if consumption_daily.empty or actual is None or actual.empty:
        return pd.DataFrame()

    theory = consumption_daily[["日期", "原料名称", "计量单位", "理论消耗量"]]
    if "单位" in actual.columns:
        act = (actual.groupby(["日期", "原料名称", "单位"], as_index=False)["消耗量"].sum()
               .rename(columns={"单位": "实际单位", "消耗量": "实际消耗量"}))
    else:
        act = (actual.groupby(["日期", "原料名称"], as_index=False)["消耗量"].sum()
               .rename(columns={"消耗量": "实际消耗量"}))

    res = theory.merge(act, on=["日期", "原料名称"], how="outer")
    res["理论消耗量"] = res["理论消耗量"].fillna(0)

    same_unit = res["实际单位"].isna() | (res["实际单位"] == res["计量单位"]) \
        if "实际单位" in res.columns else pd.Series(True, index=res.index)
    res["差异量"] = (res["实际消耗量"] - res["理论消耗量"]).round(3)
    res["差异率"] = (res["差异量"] / res["理论消耗量"].replace(0, pd.NA)).round(4)
    res["判定"] = np.where(~same_unit, "单位不一致", _diff_label(res["差异率"]))
    res.loc[~same_unit, ["差异量", "差异率"]] = np.nan
    return res.sort_values(["日期", "原料名称"]).reset_index(drop=True)


# ---------------- 原料采购建议 ----------------
def purchase_plan(summary: pd.DataFrame,
                  material: pd.DataFrame,
                  last_date: pd.Timestamp,
                  months: int = None) -> pd.DataFrame:
    """按历史日均消耗 + 安全库存，给出未来几个月的建议采购量。"""
    if summary.empty:
        return pd.DataFrame()
    months = months or config.PURCHASE_FORECAST_MONTHS

    start = (last_date.replace(day=1) + pd.DateOffset(months=1)) if pd.notna(last_date) else None
    if start is None:
        return pd.DataFrame()
    period = [start + pd.DateOffset(months=i) for i in range(months)]

    base = summary[["原料名称", "计量单位", "日均消耗量"]].copy()
    rows = []
    for month in period:
        days = calendar.monthrange(month.year, month.month)[1]
        for _, item in base.iterrows():
            need = item["日均消耗量"] * days
            safety = item["日均消耗量"] * config.SAFETY_STOCK_DAYS
            suggested = need + safety
            rows.append({
                "计划月份": f"{month.year}-{month.month:02d}",
                "原料名称": item["原料名称"],
                "计量单位": item["计量单位"],
                "日均消耗量": round(item["日均消耗量"], 3),
                "预计消耗量": round(need, 3),
                "安全库存量": round(safety, 3),
                "建议采购量": round(suggested, 3),
            })

    res = pd.DataFrame(rows)
    if material is not None and not material.empty and "数量" in material.columns:
        mat = _material_columns(material).rename(
            columns={"规格": "包装规格", "数量": "单包装含量", "单位": "原料单位"}
        )
        res = res.merge(mat, on="原料名称", how="left")
        same_unit = res["原料单位"].isna() | (res["原料单位"] == res["计量单位"])
        packed = np.where(
            same_unit & res["单包装含量"].notna() & (res["单包装含量"] > 0),
            np.ceil(res["建议采购量"] / res["单包装含量"]),
            np.nan,
        )
        res["建议采购包装数"] = packed
        res["按包装采购量"] = (res["建议采购包装数"] * res["单包装含量"]).round(3)
        res["单价"] = np.where(same_unit, res["价格"], np.nan)
        res["预计金额"] = (res["按包装采购量"].fillna(res["建议采购量"]) * res["单价"]).round(2)

    res["计算说明"] = (
        f"日均消耗 × 当月天数 + 安全库存（{config.SAFETY_STOCK_DAYS} 天日均）"
    )
    cols = ["计划月份", "原料名称", "计量单位", "日均消耗量",
            "预计消耗量", "安全库存量", "建议采购量"]
    if "包装规格" in res.columns:
        cols += ["包装规格", "单包装含量", "建议采购包装数", "按包装采购量", "单价", "预计金额"]
    cols.append("计算说明")
    return res[cols].sort_values(["计划月份", "原料名称"]).reset_index(drop=True)


# ---------------- 数据校验 ----------------
def validate_inputs(frames: dict, sales_daily: pd.DataFrame,
                    consumption_daily: pd.DataFrame) -> pd.DataFrame:
    """检查必填字段、外键完整性、金额与日期覆盖情况。"""
    from . import config as cfg

    purchases = frames.get(cfg.SHEET_PURCHASE, pd.DataFrame())
    bom = frames.get(cfg.SHEET_BOM, pd.DataFrame())
    dim = frames.get(cfg.SHEET_DATE_DIM, pd.DataFrame())
    material = frames.get(cfg.SHEET_MATERIAL, pd.DataFrame())
    actual = frames.get(cfg.SHEET_ACTUAL_CONSUMPTION, pd.DataFrame())
    product_info = frames.get(cfg.SHEET_PRODUCT_INFO, pd.DataFrame())
    name_audit = frames.get("_名称审计", pd.DataFrame())
    bom_taste = frames.get("_BOM口味审计", pd.DataFrame())

    checks = []

    def add(name, result, ok):
        checks.append((name, result, "通过" if ok else "需关注"))

    add("购买记录行数", f"{len(purchases)} 行，可用于计算 {len(derive.valid_purchases(purchases))} 行", True)
    add("日期缺失", f"{int(purchases['日期'].isna().sum())} 行", purchases["日期"].isna().sum() == 0)
    add("时间缺失（不计入客流）", f"{int(purchases['小时'].isna().sum())} 行",
        purchases["小时"].isna().sum() == 0)
    add("商品名称缺失", f"{int(purchases['商品名称'].isna().sum())} 行",
        purchases["商品名称"].isna().sum() == 0)
    add("商品编号生成缺失", f"{int(purchases['商品编号'].isna().sum())} 行",
        purchases["商品编号"].isna().sum() == 0)
    add("数量 ≤ 0", f"{int((purchases['数量'] <= 0).sum())} 行",
        (purchases["数量"] <= 0).sum() == 0)
    add("消费金额 ≤ 0", f"{int((purchases['消费金额'] <= 0).sum())} 行",
        (purchases["消费金额"] <= 0).sum() == 0)

    dup = purchases.duplicated().sum()
    add("完全重复明细", f"{int(dup)} 行", dup == 0)

    # 名称归一歧义：同一个匹配键对应多种原始写法时列出，便于人工确认。
    ambiguous = []
    if not name_audit.empty:
        variants = name_audit.groupby("名称键")["商品名称"].nunique()
        for key, count in variants[variants > 1].items():
            names = sorted(name_audit.loc[name_audit["名称键"] == key, "商品名称"].unique())
            ambiguous.append(f"{key}→{'/'.join(names)}")
    add("商品名称归一后重名歧义",
        f"{len(ambiguous)} 个：{ambiguous or '无'}", len(ambiguous) == 0)

    # 商品信息是否覆盖购买记录 + BOM 的商品全集，且编号唯一。
    all_keys = set(purchases["名称键"].dropna()) | set(bom["名称键"].dropna())
    info_keys = set(product_info["名称键"].dropna()) if not product_info.empty else set()
    uncovered = sorted(all_keys - info_keys)
    add("商品信息覆盖全部商品",
        f"{len(product_info)} 个商品；未覆盖 {len(uncovered)} 个：{uncovered or '无'}",
        len(uncovered) == 0)
    duplicated_ids = (int(product_info["商品编号"].duplicated().sum())
                      if not product_info.empty else 0)
    add("商品信息编号唯一", f"{duplicated_ids} 个重复编号", duplicated_ids == 0)

    # 口味完整性：每个商品都应从 BOM 拿到 甜/咸/辣/原味 之一，不推断、不默认甜。
    if not product_info.empty:
        missing_product_taste = sorted(
            product_info.loc[product_info["口味风格"].isna(), "商品名称"].dropna())
        add("商品口味缺失",
            f"{len(missing_product_taste)} 个：{missing_product_taste or '无'}"
            "（请在该商品的 BOM 行填写口味）",
            len(missing_product_taste) == 0)

    sold_names = set(purchases["商品名称"].dropna())
    bom_names = set(bom["商品名称"].dropna())
    unknown_products = sorted(sold_names - bom_names) if not bom.empty else sorted(sold_names)
    add("购买商品未在 BOM 中",
        f"{len(unknown_products)} 个：{unknown_products or '无'}（缺失商品请在「商品原料信息」补 BOM）",
        len(unknown_products) == 0)

    if not bom.empty and not purchases.empty:
        not_sold = sorted(bom_names - sold_names)
        add("BOM 商品无销售记录", f"{len(not_sold)} 个：{not_sold or '无'}", len(not_sold) == 0)

    if not material.empty:
        missing_mat = sorted(set(bom["原材料"].dropna()) - set(material["原料名称"].dropna()))
        add("BOM 原料不在原材料信息", f"{len(missing_mat)} 个：{missing_mat or '无'}",
            len(missing_mat) == 0)

    # BOM 口味：缺失 / 取值非法 / 同一商品多行口味冲突。
    if not bom_taste.empty:
        missing_rows = bom_taste[bom_taste["口味编码"].isna() & bom_taste["口味"].isna()]
        invalid_rows = bom_taste[bom_taste["口味编码"].isna() & bom_taste["口味"].notna()]
        missing_products = sorted(missing_rows["商品名称"].dropna().unique())
        invalid_detail = sorted(
            f"{p}/{m}→{v}" for p, m, v in
            zip(invalid_rows["商品名称"], invalid_rows["原材料"], invalid_rows["口味"])
            if pd.notna(p)
        )
        conflicts = []
        for name, group in bom_taste.dropna(subset=["口味编码"]).groupby("商品名称"):
            codes = sorted({int(c) for c in group["口味编码"]})
            if len(codes) > 1:
                conflicts.append(
                    f"{name}：{'/'.join(cfg.TASTE_MAP.get(c, str(c)) for c in codes)}")
        add("BOM 口味缺失",
            f"{len(missing_rows)} 行 / 涉及 {len(missing_products)} 个商品："
            f"{missing_products or '无'}（请在「商品原料信息」补口味）",
            len(missing_rows) == 0)
        add("BOM 口味非法",
            f"{len(invalid_detail)} 个：{invalid_detail or '无'}（只允许 甜/咸/辣/原味）",
            len(invalid_detail) == 0)
        add("同商品口味冲突",
            f"{len(conflicts)} 个：{conflicts or '无'}", len(conflicts) == 0)

    if not dim.empty and not purchases.empty:
        out_of_dim = purchases[(purchases["日期"].notna()) &
                               (~purchases["日期"].isin(dim["日期"]))]
        add("日期超出日期维度表", f"{len(out_of_dim)} 行", len(out_of_dim) == 0)

    if sales_daily.empty:
        add("单日销量计算", "无结果，请检查购买记录与商品原料信息", False)
    else:
        add("单日销量计算", f"{sales_daily['日期'].nunique()} 天 / {sales_daily['商品编号'].nunique()} 个商品", True)

    if consumption_daily.empty:
        add("原料理论消耗计算", "无结果，请检查 BOM 商品名称是否能匹配", False)
    else:
        add("原料理论消耗计算", f"{consumption_daily['原料名称'].nunique()} 种原料", True)

    if actual.empty:
        checks.append(("实际消耗对比", "未接入「原料实际消耗」数据", "未接入"))
    else:
        checks.append(("实际消耗对比", f"{len(actual)} 条实际消耗记录", "已接入"))

    return pd.DataFrame(checks, columns=["校验项", "结果", "状态"])
