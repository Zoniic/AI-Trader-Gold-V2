"""ดึงข้อมูลย้อนหลังจาก MT5 terminal แล้ว cache เป็น parquet — รันแยกต่างหาก ไม่ได้ถูกเรียกอัตโนมัติ

ใช้งาน: python -m data.mt5_loader
ต้องมี MT5 terminal ติดตั้งและ login ได้ในเครื่องนี้ (Windows เท่านั้น)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import Settings, load_settings

TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def fetch_history(settings: Settings) -> pd.DataFrame:
    import MetaTrader5 as mt5

    # ถ้าไม่ได้ตั้ง MT5_LOGIN ใน .env ให้เกาะกับ terminal ที่เปิด+login อยู่แล้วในเครื่อง
    # (mt5.initialize() ปฏิเสธ login=None แบบเจาะจง ต้องไม่ส่ง kwargs พวกนี้เลยถ้าไม่มีค่าจริง)
    if settings.mt5.login is not None:
        connected = mt5.initialize(
            login=settings.mt5.login, password=settings.mt5.password, server=settings.mt5.server
        )
    else:
        connected = mt5.initialize()

    if not connected:
        raise ConnectionError(f"เชื่อมต่อ MT5 ไม่สำเร็จ: {mt5.last_error()}")

    try:
        timeframe = getattr(mt5, TIMEFRAME_MAP[settings.timeframe])
        date_from = pd.Timestamp(settings.start_date)
        date_to = pd.Timestamp(settings.end_date)
        rates = mt5.copy_rates_range(settings.symbol, timeframe, date_from, date_to)
        if rates is None or len(rates) == 0:
            raise RuntimeError(
                f"ไม่มีข้อมูลสำหรับ {settings.symbol} {settings.timeframe} "
                f"({settings.start_date} - {settings.end_date}) — เช็คชื่อ symbol ของโบรกให้ตรง"
            )
    finally:
        mt5.shutdown()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time").rename(columns={"tick_volume": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def save_to_cache(settings: Settings) -> Path:
    df = fetch_history(settings)
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / f"{settings.symbol}_{settings.timeframe}.parquet"
    df.to_parquet(out_path)
    print(f"[mt5_loader] บันทึก {len(df)} แท่งเทียน -> {out_path}")
    return out_path


if __name__ == "__main__":
    save_to_cache(load_settings())
