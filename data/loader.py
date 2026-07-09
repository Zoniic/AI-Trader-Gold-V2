"""โหลดข้อมูลราคาให้ backtest ใช้ ลำดับความสำคัญ: parquet ในเครื่อง -> csv ในเครื่อง -> ดึงสดจาก MT5

ทำให้พัฒนาต่อได้แม้เครื่องนี้ไม่มี MT5 ติดตั้ง แค่วางไฟล์ CSV ไว้ที่ data_files/
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import Settings
from core.signal import MarketData

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def _validate(df: pd.DataFrame, source: str) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{source}: ขาดคอลัมน์ {missing} (ต้องมี {REQUIRED_COLUMNS})")
    return df.sort_index()


def _from_parquet(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index("time")
        df.index = pd.to_datetime(df.index)
    return _validate(df, str(path))


def _from_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["time"]).set_index("time")
    return _validate(df, str(path))


def _from_mt5(settings: Settings) -> pd.DataFrame:
    from data.mt5_loader import fetch_history  # import here: MetaTrader5 อาจไม่มีในเครื่อง

    return fetch_history(settings)


def load_price_data(settings: Settings) -> MarketData:
    data_dir = Path(settings.data_dir)
    parquet_path = data_dir / f"{settings.symbol}_{settings.timeframe}.parquet"
    csv_path = data_dir / f"{settings.symbol}_{settings.timeframe}.csv"

    if parquet_path.exists():
        print(f"[data] โหลดจาก parquet: {parquet_path}")
        df = _from_parquet(parquet_path)
    elif csv_path.exists():
        print(f"[data] โหลดจาก csv: {csv_path}")
        df = _from_csv(csv_path)
    else:
        try:
            import MetaTrader5  # noqa: F401
        except ImportError as exc:
            raise FileNotFoundError(
                f"ไม่พบไฟล์ข้อมูลที่ {parquet_path} หรือ {csv_path} และไม่มีแพ็กเกจ MetaTrader5 "
                "ติดตั้งอยู่ — วางไฟล์ CSV/parquet ไว้ที่โฟลเดอร์นั้น หรือติดตั้ง MetaTrader5 "
                "แล้วรัน `python -m data.mt5_loader` ก่อน"
            ) from exc
        print("[data] ไม่พบไฟล์ในเครื่อง ดึงสดจาก MT5 ...")
        df = _validate(_from_mt5(settings), "MT5 live pull")

    return MarketData(df=df, symbol=settings.symbol)
