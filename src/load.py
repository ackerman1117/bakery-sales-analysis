"""数据读取层：把 Excel 各 sheet 读成 DataFrame。"""

from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from . import config


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
    """读取单个 sheet，去掉全空行。"""
    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    df = df.dropna(how="all")
    return df


def load_all(path: Optional[Path] = None) -> Dict[str, pd.DataFrame]:
    """读取全部业务 sheet，返回 {sheet 名: DataFrame}。"""
    data_path = resolve_data_path(path)
    xls = pd.ExcelFile(data_path, engine="openpyxl")
    available = set(xls.sheet_names)

    frames: Dict[str, pd.DataFrame] = {}
    for name in config.BUSINESS_SHEETS:
        if name in available:
            frames[name] = read_sheet(data_path, name)
        else:
            frames[name] = pd.DataFrame()
    frames["_source"] = pd.DataFrame({"file": [str(data_path)]})
    return frames


if __name__ == "__main__":
    data = load_all()
    print(f"数据源：{data['_source'].iloc[0, 0]}")
    for name, df in data.items():
        if name.startswith("_"):
            continue
        print(f"{name}: {len(df)} 行 x {len(df.columns)} 列")
