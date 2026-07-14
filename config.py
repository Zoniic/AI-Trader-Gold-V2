"""จุดรวมค่าตั้งค่าทั้งหมดของโปรเจกต์ อ่านจาก .env ครั้งเดียวตอน import"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# คอนโซล Windows บาง locale ใช้ cp1252 ซึ่ง encode ข้อความไทยไม่ได้ บังคับ utf-8 ไว้ก่อน
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class MT5Credentials:
    login: int | None
    password: str | None
    server: str | None


@dataclass(frozen=True)
class Settings:
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    data_dir: str
    reports_dir: str
    log_db_path: str
    initial_balance: float
    risk_per_trade_pct: float
    max_drawdown_pct: float
    spread_points: float
    slippage_points: float
    point_value: float  # ขนาด 1 point เป็นหน่วยราคา (GOLD=0.01, EURUSD=0.00001)
    contract_size: float  # ขนาดสัญญาต่อ 1 lot (GOLD=100 oz, EURUSD=100000)
    discord_webhook_url: str | None
    discord_webhook_url_dry_run: str | None
    mt5: MT5Credentials


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def load_settings() -> Settings:
    mt5_login = os.getenv("MT5_LOGIN")
    return Settings(
        symbol=os.getenv("SYMBOL", "XAUUSD"),
        timeframe=os.getenv("TIMEFRAME", "H1"),
        start_date=os.getenv("START_DATE", "2023-01-01"),
        end_date=os.getenv("END_DATE", "2026-07-01"),
        data_dir=os.getenv("DATA_DIR", str(BASE_DIR / "data_files")),
        reports_dir=os.getenv("REPORTS_DIR", str(BASE_DIR / "reports")),
        log_db_path=os.getenv("LOG_DB_PATH", str(BASE_DIR / "trading_log.db")),
        initial_balance=_env_float("INITIAL_BALANCE", 10000.0),
        risk_per_trade_pct=_env_float("RISK_PER_TRADE_PCT", 1.0),
        max_drawdown_pct=_env_float("MAX_DRAWDOWN_PCT", 20.0),
        spread_points=_env_float("SPREAD_POINTS", 30.0),
        slippage_points=_env_float("SLIPPAGE_POINTS", 5.0),
        # instrument spec ต่อสินทรัพย์ — ดีฟอลต์เป็นค่า GOLD (สินทรัพย์หลักเดิม) ถ้ารันสินทรัพย์อื่น
        # ต้องตั้ง env ให้ตรงโบรก เช่น EURUSD: POINT_VALUE=0.00001 CONTRACT_SIZE=100000 SPREAD_POINTS=12
        point_value=_env_float("POINT_VALUE", 0.01),
        contract_size=_env_float("CONTRACT_SIZE", 100.0),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
        # webhook แยกกันตั้งใจ — dry-run/backtest กับ live ยิงเข้าคนละช่อง Discord กัน ไม่งั้นตอนทดสอบ
        # dry-run ถี่ๆ จะไปปนกับข้อความไม้จริงในช่องเดียวกัน ทำให้แยกไม่ออกว่าอันไหนเงินจริง
        discord_webhook_url_dry_run=os.getenv("DISCORD_WEBHOOK_URL_DRY_RUN") or None,
        mt5=MT5Credentials(
            login=int(mt5_login) if mt5_login else None,
            password=os.getenv("MT5_PASSWORD"),
            server=os.getenv("MT5_SERVER"),
        ),
    )
