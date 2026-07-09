"""Entrypoint: จำลองพอร์ตรวมทุกทีม + ทดสอบตัวคูณความเสี่ยงหลายระดับ

ใช้งาน: python run_portfolio.py [--multipliers 1,2,4,8]
ตอบคำถาม "อยากได้ X%/เดือน ต้องเร่ง risk เท่าไหร่ และ DD/โอกาสเจ๊งเป็นเท่าไหร่" ด้วยข้อมูลจริง
"""
from __future__ import annotations

import argparse

from config import load_settings
from portfolio.simulate import simulate_portfolio

# รอบ5: คัดใหม่หลัง snowball grid — ทุกทีมผ่าน walk-forward แล้ว, risk% ตาม tier ความสม่ำเสมอ
# (1.0%=5/5 fold บวก, 0.5%=4-5/5, 0.25%=3/5 — กระจายสำนักกลยุทธ์กันสหสัมพันธ์สูง ตาม SOP ข้อ 25)
CORE_SELECTIONS = [
    ("trend_pullback", "M30", 1.0),      # เทรนด์ย่อ — 5/5 fold, ข้อมูลตั้งแต่ 2024-01
    ("london_breakout", "M30", 1.0),     # session breakout — พิสูจน์แล้วรอบก่อน, 2024-01
    ("trend_pullback", "H1", 0.5),       # เทรนด์ย่อ TF ยาวกว่า — ข้อมูลตั้งแต่ 2023-01 (คนละคาบกับ M30)
    ("rsi_divergence", "M30", 0.5),      # momentum divergence — ข้อมูลตั้งแต่ 2024-01
    ("donchian_breakout", "H1", 0.5),    # breakout ล้วน — 4/5 fold, 2023-01
    ("ema_cross", "M30", 0.5),           # เทรนด์ตาม EMA — 4/4 fold, 2024-01
    ("vwap_reversion", "H1", 0.25),      # mean-reversion — 3/5 fold (อ่อนกว่า), 2023-01
    ("volatility_breakout", "H1", 0.25), # breakout ผันผวน — 3/5 fold (อ่อนกว่า), 2023-01
]
# หมายเหตุ: fib_confluence M30 ผ่าน walk-forward (4/5) แต่ทดสอบแล้วว่า "เจือจาง" พอร์ตนี้ —
# เพิ่มเข้าไปทำให้ final 34k->28-29k, MaxDD 14.1%->15% ทุกระดับ max_concurrent (ไม้มันแข่ง
# slot กับทีม expectancy สูงกว่า ไม่ได้กระจายความเสี่ยงจริง) — เก็บไว้เทรดเดี่ยว/พอร์ตอื่นแทน
# หมายเหตุ: หลีกเลี่ยงทีม M15 (london_breakout/rsi_divergence M15) เพราะข้อมูล M15 เริ่มแค่ปี 2025-07
# — ถ้าใส่เข้าไป หน้าต่างเวลาร่วมของพอร์ต (intersection) จะหดเหลือ ~12 เดือนแทน 2.5 ปี ทำให้ stress
# test ที่ multiplier สูงดูปลอดภัยเกินจริง (ไม่เจอสถานการณ์เลวร้ายในอดีตเหมือนพอร์ตช่วงยาว)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--multipliers", default="1,2,4,8")
    parser.add_argument("--max-concurrent", type=int, default=3)
    parser.add_argument("--max-same-direction", type=int, default=2)
    parser.add_argument("--daily-loss-limit", type=float, default=5.0)
    parser.add_argument(
        "--no-dd-targeting", action="store_true",
        help="ปิดการหด/ขยาย lot ตามพื้นที่ว่างก่อนชนเพดาน DD (ดีฟอลต์เปิด — ช่วยกันบัญชีเจ๊งตอน over-leverage)",
    )
    args = parser.parse_args()
    dd_targeting = not args.no_dd_targeting

    settings = load_settings()
    multipliers = [float(m) for m in args.multipliers.split(",")]

    print("ทีมในพอร์ต:", ", ".join(f"{s}:{tf} (risk {r}%)" for s, tf, r in CORE_SELECTIONS))
    print(
        f"กติกา: เปิดพร้อมกันสูงสุด {args.max_concurrent} ไม้ · ทิศเดียวกันสูงสุด "
        f"{args.max_same_direction} · daily lock {args.daily_loss_limit}%\n"
    )

    header = (
        f"{'คูณ':>4s} {'ทุนจบ':>12s} {'MaxDD%':>7s} {'เดือนเฉลี่ย%':>11s} "
        f"{'เดือนแย่สุด%':>11s} {'เดือนดีสุด%':>11s} {'ไม้':>5s} {'เจ๊ง?':>5s}"
    )
    print(header)
    for m in multipliers:
        result = simulate_portfolio(
            settings.log_db_path,
            CORE_SELECTIONS,
            initial_balance=settings.initial_balance,
            risk_multiplier=m,
            max_concurrent=args.max_concurrent,
            max_same_direction=args.max_same_direction,
            daily_loss_limit_pct=args.daily_loss_limit,
            dd_targeting=dd_targeting,
        )
        rets = [mo["return_pct"] for mo in result.monthly_returns]
        avg = sum(rets) / len(rets) if rets else 0
        print(
            f"{m:4.0f} {result.final_balance:12,.0f} {result.max_drawdown_pct:7.1f} "
            f"{avg:11.1f} {min(rets) if rets else 0:11.1f} {max(rets) if rets else 0:11.1f} "
            f"{result.taken:5d} {'ใช่!' if result.ruined else 'ไม่':>5s}"
        )

    # รายเดือนของตัวคูณ 1x ให้เห็นจังหวะจริง
    base = simulate_portfolio(
        settings.log_db_path, CORE_SELECTIONS,
        initial_balance=settings.initial_balance, risk_multiplier=1.0,
        max_concurrent=args.max_concurrent, max_same_direction=args.max_same_direction,
        daily_loss_limit_pct=args.daily_loss_limit, dd_targeting=dd_targeting,
    )
    print("\nรายเดือน (ตัวคูณ 1x):")
    for mo in base.monthly_returns:
        print(f"  {mo['month']}: {mo['return_pct']:+6.1f}%  (equity {mo['equity']:,.0f})")
    print(
        f"\nข้ามไม้เพราะ: เปิดครบ {base.skipped_concurrent} · ทิศซ้ำ {base.skipped_direction} · "
        f"daily lock {base.skipped_daily_lock}"
    )


if __name__ == "__main__":
    main()
