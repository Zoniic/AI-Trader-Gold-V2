"""config ต่อทีมในโฟลเดอร์ configs/ — ทุกผลรันผูกกับ setting ที่ใช้เสมอ (บันทึกลง DB ด้วย)

ไฟล์ configs/<team>.json สร้างอัตโนมัติครั้งแรกจากค่า default ของทีม แก้ไฟล์แล้วรันใหม่
ได้เลยไม่ต้องแตะโค้ด — สนามทดลองปรับจูนที่ตามรอยได้ว่าผลไหนมาจาก setting ไหน
"""
from __future__ import annotations

import json
from pathlib import Path

from config import BASE_DIR

CONFIGS_DIR = BASE_DIR / "configs"

DEFAULT_TRADE_MANAGEMENT = {
    "partial_tp_r": None,  # ปิดบางส่วนเมื่อกำไรถึงกี่ R (null = ปิดทีเดียวที่ TP)
    "partial_fraction": 0.5,
    "move_sl_to_breakeven": True,
    "trailing_stop_r": None,  # ระยะลาก SL ตาม extreme (หน่วย R, null = ไม่ใช้)
    "trailing_activate_r": 1.0,
    "remove_tp_when_trailing": False,  # true = snowball เต็มรูปแบบ (ตัด TP ทิ้งเมื่อ trailing ทำงาน)
}


def load_team_config(team_name: str, strategy_cls, timeframe: str | None = None) -> dict:
    """โหลด config ของทีม — ลำดับ: configs/<team>_<TF>.json (ถ้ามี) > configs/<team>.json > default

    ทำให้จูนแยกต่อ timeframe ได้ (เช่น M15 ต้องการตัวกรองเข้มกว่า H1) โดยไม่กระทบ TF อื่น
    """
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    base_path = CONFIGS_DIR / f"{team_name}.json"
    tf_path = CONFIGS_DIR / f"{team_name}_{timeframe}.json" if timeframe else None

    if tf_path is not None and tf_path.exists():
        path = tf_path
    elif base_path.exists():
        path = base_path
    else:
        default_cfg = {
            "strategy_params": strategy_cls().params(),
            "trade_management": dict(DEFAULT_TRADE_MANAGEMENT),
            "notes": "แก้ค่าในไฟล์นี้แล้วรัน backtest ใหม่ได้เลย ทุก run บันทึก config ลง DB ให้ตามรอยได้",
        }
        base_path.write_text(
            json.dumps(default_cfg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return default_cfg

    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("strategy_params", {})
    # merge default เผื่อ config เก่าที่สร้างก่อนมี key ใหม่ (เช่น trailing_stop_r)
    cfg["trade_management"] = {**DEFAULT_TRADE_MANAGEMENT, **cfg.get("trade_management", {})}
    cfg.setdefault("allowed_regimes", None)  # จำกัดทีมให้เทรดเฉพาะ regime ที่ถนัด (null = ทุกสภาวะ)
    cfg.setdefault("min_approvals", 4)  # เสียงอนุมัติขั้นต่ำของคณะกรรมการ (5 = ต้องเอกฉันท์)
    cfg.setdefault("risk", None)  # override risk ต่อทีม: {risk_per_trade_pct, max_daily_loss_pct, max_weekly_loss_pct, max_drawdown_pct, sizing_mode}
    cfg.setdefault("strategy_review", None)  # {edge, best_market, avoid_when} — โชว์บนเว็บ
    cfg["_config_file"] = path.name  # ให้ snapshot บอกได้ว่าใช้ไฟล์ไหน
    return cfg
