"""一键跑全部分析：加载 → 清洗 → 派生 → 分析 → 输出。

用法：
    python -m src.run_all
    python -m src.run_all --data path/to/food.xlsx

数据模型：购买记录 是唯一事实表，商品原料信息 + 日期维度表 是维度表，
不读取 Excel 中任何已经算好的结果 sheet。
"""

import argparse
from pathlib import Path

import pandas as pd

from . import analysis, clean, config, derive, load


def _print_block(title: str, df: pd.DataFrame) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    if df is None or df.empty:
        print("（无数据）")
        return
    print(df.to_string(index=False))


def _save(df: pd.DataFrame, name: str) -> None:
    if df is None or df.empty:
        return
    config.OUT_TABLES.mkdir(parents=True, exist_ok=True)
    path = config.OUT_TABLES / f"{name}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  已保存 {path.name}")


def build_results(frames: dict) -> dict:
    """由清洗后的输入计算全部结果表。"""
    purchases = frames.get(config.SHEET_PURCHASE, pd.DataFrame())
    bom = frames.get(config.SHEET_BOM, pd.DataFrame())
    material = frames.get(config.SHEET_MATERIAL, pd.DataFrame())
    actual = frames.get(config.SHEET_ACTUAL_CONSUMPTION, pd.DataFrame())
    product_info = frames.get(config.SHEET_PRODUCT_INFO, pd.DataFrame())

    # 1. 基础派生：全部来自购买记录
    sales_daily = derive.daily_product_sales(purchases)
    hourly = derive.hourly_traffic(purchases)
    daily = analysis.daily_summary(purchases)
    product_pref = derive.product_preference(purchases, sales_daily)
    taste_pref = derive.taste_preference(purchases)
    consumption_daily = derive.material_consumption_daily(purchases, bom, sales_daily)

    # 2. 经营分析：在派生结果上做汇总与建议
    pattern = analysis.traffic_pattern(hourly, daily)
    observed_days = int(daily["日期"].nunique()) if not daily.empty else 1
    mat_summary = analysis.material_summary(consumption_daily, material, actual, observed_days)
    last_date = purchases["日期"].max() if not purchases.empty else pd.NaT
    purchase_suggest = analysis.purchase_plan(mat_summary, material, last_date)
    actual_cmp = analysis.actual_vs_theoretical(consumption_daily, actual)

    return {
        "商品信息": product_info[["商品编号", "商品名称", "口味风格", "口味", "商品类别"]]
        if not product_info.empty else product_info,
        "销售概览": analysis.sales_kpis(purchases, sales_daily),
        "单日产品销售量": sales_daily,
        "产品偏好": product_pref,
        "口味偏好": taste_pref,
        "客流量_分时段": hourly,
        "客流规律_分星期": pattern,
        "小时工排班建议": analysis.staffing_plan(pattern),
        "节假日效应": analysis.holiday_effect(daily),
        "原料理论消耗": consumption_daily,
        "原料消耗汇总": mat_summary,
        "原料采购建议": purchase_suggest,
        "实际与理论消耗对比": actual_cmp,
        "数据校验": analysis.validate_inputs(frames, sales_daily, consumption_daily),
    }


def run(data_path: Path = None) -> dict:
    """执行完整分析流程，返回各分析结果。"""
    frames = load.load_all(data_path)
    frames = clean.clean_all(frames)
    results = build_results(frames)

    print(f"数据源：{frames['_source'].iloc[0, 0]}")
    if not frames["_ignored"].empty:
        print(f"已忽略的 sheet（不参与计算）：{'、'.join(frames['_ignored']['sheet'])}")
    for title, df in results.items():
        _print_block(title, df)

    print(f"\n{'=' * 60}\n写出结果文件\n{'=' * 60}")
    for title, df in results.items():
        _save(df, title)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="面包店数据分析")
    parser.add_argument("--data", type=str, default=None, help="Excel 数据文件路径")
    args = parser.parse_args()
    run(Path(args.data) if args.data else None)


if __name__ == "__main__":
    main()
