"""数据读取层：只读取输入表，不读取任何预先算好的结果表。"""

from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from . import config


class DataSchemaError(ValueError):
    """输入文件缺少必需 sheet 或必需字段。"""


def resolve_data_path(path: Optional[Path] = None) -> Path:
    """优先读取 data/raw/food.xlsx，不存在时回退到样例数据。"""
    if path is not None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"数据文件不存在：{p}")
        return p

    if config.DATA_RAW.exists():
        return config.DATA_RAW
    if config.DATA_SAMPLE.exists():
        return config.DATA_SAMPLE
    raise FileNotFoundError(
        "未找到数据文件。请把 Excel 放到 data/raw/food.xlsx，"
        "或使用仓库自带的 data/sample/sample_food.xlsx"
    )


def read_sheet(path: Path, sheet_name: str) -> pd.DataFrame:
    """读取单个 sheet，去空行、去重表头、列名去空格。"""
    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def load_all(path: Optional[Path] = None) -> Dict[str, pd.DataFrame]:
    """读取输入表。

    必需：购买记录、商品原料信息、日期维度表
    可选：原材料信息、原料实际消耗、原料采购记录
    """
    data_path = resolve_data_path(path)
    xls = pd.ExcelFile(data_path, engine="openpyxl")
    available = set(xls.sheet_names)

    missing = [name for name in config.REQUIRED_SHEETS if name not in available]
    if missing:
        raise DataSchemaError(
            f"缺少必需 sheet：{'、'.join(missing)}。"
            f"当前文件包含：{'、'.join(xls.sheet_names)}"
        )

    frames: Dict[str, pd.DataFrame] = {}
    for name in config.REQUIRED_SHEETS + config.OPTIONAL_SHEETS:
        frames[name] = read_sheet(data_path, name) if name in available else pd.DataFrame()

    missing_cols = [
        col for col in config.PURCHASE_REQUIRED_COLUMNS
        if col not in frames[config.SHEET_PURCHASE].columns
    ]
    if missing_cols:
        raise DataSchemaError(
            f"「{config.SHEET_PURCHASE}」缺少必需字段：{'、'.join(missing_cols)}。"
            "源表只维护商品名称，商品编号由程序生成。"
        )

    missing_bom_cols = [
        col for col in config.BOM_REQUIRED_COLUMNS
        if col not in frames[config.SHEET_BOM].columns
    ]
    if missing_bom_cols:
        raise DataSchemaError(
            f"「{config.SHEET_BOM}」缺少必需字段：{'、'.join(missing_bom_cols)}。"
            "BOM 需要商品名称 + 原材料 + 用量 + 口味；口味是商品级属性，"
            "同一商品所有 BOM 行填同一个值（甜 / 咸 / 辣 / 原味），商品编号由程序生成。"
        )

    ignored = [name for name in xls.sheet_names if name in config.IGNORED_SHEETS]
    frames["_source"] = pd.DataFrame({"file": [str(data_path)]})
    frames["_ignored"] = pd.DataFrame({"sheet": ignored})
    return frames


if __name__ == "__main__":
    data = load_all()
    print(f"数据源：{data['_source'].iloc[0, 0]}")
    if not data["_ignored"].empty:
        print(f"已忽略：{'、'.join(data['_ignored']['sheet'])}")
    for name, df in data.items():
        if name.startswith("_"):
            continue
        print(f"{name}: {len(df)} 行 x {len(df.columns)} 列" if not df.empty else f"{name}: （无）")
