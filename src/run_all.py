"""一键跑全部分析：加载 → 清洗 → 分析 → 输出。

用法：
    python -m src.run_all
    python -m src.run_all --data path/to/food.xlsx
"""

import argparse
from pathlib import Path

import pandas as pd

from . import analysis, clean, config, load


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


def run(data_path: Path = None) -> dict:
    """执行完整分析流程，返回各分析结果。"""
    frames = load.load_all(data_path)
    frames = clean.clean_all(frames)

    sales = frames.get(config.SHEET_DAILY_SALES, pd.DataFrame())
    purchases = frames.get(config.SHEET_PURCHASE, pd.DataFrame())
    production = frames.get(config.SHEET_PRODUCTION, pd.DataFrame())
    consumption = frames.get(config.SHEET_CONSUMPTION, pd.DataFrame())
    purchase_monthly = frames.get(config.SHEET_PURCHASE_MONTHLY, pd.DataFrame())
    traffic = frames.get(config.SHEET_TRAFFIC, pd.DataFrame())
    bom = frames.get(config.SHEET_BOM, pd.DataFrame())
    material = frames.get(config.SHEET_MATERIAL, pd.DataFrame())
    taste_pref = frames.get(config.SHEET_TASTE_PREF, pd.DataFrame())
    product_pref = frames.get(config.SHEET_PRODUCT_PREF, pd.DataFrame())

    results = {
        "销售概览": analysis.sales_kpis(purchases, sales),
        "产品排名": analysis.product_ranking(sales),
        "口味偏好": analysis.taste_ranking(sales, bom),
        "节假日效应": analysis.holiday_effect(sales),
        "生产与销售匹配": analysis.production_vs_sales(production, sales),
        "原料消耗": analysis.material_consumption(consumption, material),
        "采购与消耗对比": analysis.purchase_vs_consumption(purchase_monthly, consumption),
        "客流时段分布": analysis.traffic_analysis(traffic),
        "结果表校验": analysis.check_result_tables(sales, taste_pref, product_pref),
    }

    print(f"数据源：{frames['_source'].iloc[0, 0]}")
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
