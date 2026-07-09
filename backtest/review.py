"""นักวิเคราะห์หลังจบไม้ — ทุกไม้ต้องถูกรีวิวว่าแพ้/ชนะเพราะอะไร และควรปรับ SL/TP ยังไง

ใช้ 3 ตัวเลขหลักที่มืออาชีพใช้วิเคราะห์คุณภาพ SL/TP:
- pnl_r  : กำไร/ขาดทุนจริงเป็นเท่าของความเสี่ยง (R multiple) หลังหักต้นทุนแล้ว
- mae_r  : Maximum Adverse Excursion — ระหว่างถือ ราคาเคยสวนเราลึกสุดกี่ R
- mfe_r  : Maximum Favorable Excursion — ระหว่างถือ ราคาเคยเป็นใจให้เราไกลสุดกี่ R
และ post_exit_r: หลังปิดไม้ที่ชน TP แล้ว ราคาวิ่ง "ต่อ" อีกกี่ R (ใช้ตอบว่า TP ต่ำไป/ควร snowball ไหม
— เป็นการวิเคราะห์ย้อนหลังเท่านั้น ไม่ได้ใช้ตัดสินใจเทรด จึงไม่ใช่ lookahead bias)
"""
from __future__ import annotations


def review_trade(
    outcome: str, pnl_r: float, mae_r: float, mfe_r: float, post_exit_r: float | None
) -> str:
    """สร้างข้อความวิเคราะห์รายไม้เป็นภาษาคน จากตัวเลขจริงของไม้นั้น"""
    parts: list[str] = []

    if outcome in ("tp", "tp_after_partial"):
        parts.append(f"ชนะที่ TP ได้ {pnl_r:+.2f}R")
        if mae_r >= 0.8:
            parts.append(f"แต่ระหว่างทางราคาสวนลึกถึง -{mae_r:.1f}R เฉียด SL มาก — ไม้แนวนี้ SL แคบกว่านี้ไม่ได้แล้ว")
        elif mae_r <= 0.3:
            parts.append(f"ราคาแทบไม่ย้อนเลย (แค่ -{mae_r:.1f}R) — setup แบบนี้ขยับ SL แคบลงได้ จะได้ R:R สูงขึ้น")
        if post_exit_r is not None and post_exit_r >= 1.0:
            parts.append(f"หลังปิด ราคายังวิ่งต่ออีก +{post_exit_r:.1f}R — TP ต่ำไปสำหรับไม้แบบนี้ (เข้าทาง snowball/trailing)")
    elif outcome == "sl":
        parts.append(f"แพ้ที่ SL {pnl_r:+.2f}R")
        if mfe_r >= 1.0:
            parts.append(f"ทั้งที่เคยกำไรถึง +{mfe_r:.1f}R ก่อนกลับมาโดน SL — partial TP ที่ 1R + เลื่อน SL ไป BE จะกู้ไม้แบบนี้ได้")
        elif mfe_r >= 0.5:
            parts.append(f"เคยกำไร +{mfe_r:.1f}R แล้วหลุดมือ — ลอง partial TP เร็วขึ้นหรือ TP ใกล้ลง")
        else:
            parts.append(f"ผิดทางเกือบทันที (ไปได้ไกลสุดแค่ +{mfe_r:.1f}R) — ปัญหาอยู่ที่เงื่อนไขเข้า ไม่ใช่ SL/TP")
    elif outcome == "trailing_stop":
        parts.append(f"ออกด้วย trailing stop ที่ {pnl_r:+.2f}R (วิ่งไกลสุด +{mfe_r:.1f}R)")
        if pnl_r > 0 and mfe_r - pnl_r > 1.0:
            parts.append(f"คืนกำไรไป {mfe_r - pnl_r:.1f}R ก่อนโดนลาก — ลองลดระยะ trailing ให้แคบลง")
    elif outcome == "be_after_partial":
        parts.append(f"เก็บ partial แล้วโดน SL ที่ BE ปิดรวม {pnl_r:+.2f}R — ระบบป้องกันทำงานตามแผน")
    else:  # timeout / end_of_data
        parts.append(f"ถือจนหมดเวลา ปิดที่ {pnl_r:+.2f}R (ไปได้ไกลสุด +{mfe_r:.1f}R / สวนลึกสุด -{mae_r:.1f}R)")
        if mfe_r >= 1.0:
            parts.append("ราคาเคยไปไกลแต่ไม่ถึง TP — TP ไกลเกินไปสำหรับ setup นี้")

    return " ".join(parts)


def score_trade(
    outcome: str, pnl_r: float, mae_r: float, mfe_r: float, dissents: int
) -> tuple[int, str]:
    """Scorecard 60 คะแนน ต่อไม้ (6 หมวด × 10) — วัดคุณภาพการเทรด ไม่ใช่แค่กำไร

    Entry: ไม้ไปถูกทางแค่ไหน (MFE) · SL: ตั้งเหมาะไหม · RR: เก็บได้กี่ R ·
    วินัย: มติทีมเอกฉันท์ไหม · จัดการไม้: ออกตามแผนไหม · ประสิทธิภาพ: เก็บได้กี่ % ของที่ราคาให้
    """
    # Entry quality — ราคาไปทางเราได้ไกลแค่ไหนหลังเข้า
    if mfe_r >= 1.0:
        entry = 10
    elif mfe_r >= 0.5:
        entry = 7
    elif mfe_r >= 0.3:
        entry = 4
    else:
        entry = 1

    # SL quality
    if pnl_r > 0:
        sl_score = 10 if mae_r <= 0.3 else 7 if mae_r <= 0.6 else 4 if mae_r <= 0.9 else 2
    else:
        # แพ้แบบผิดทางเร็ว = SL ทำหน้าที่ถูกต้อง / แพ้ทั้งที่เคยกำไรมาก = การจัดการแย่
        sl_score = 8 if mfe_r < 0.3 else 5 if mfe_r < 1.0 else 2

    # RR ที่เก็บได้จริง
    if pnl_r >= 2.0:
        rr = 10
    elif pnl_r >= 1.0:
        rr = 8
    elif pnl_r > 0:
        rr = 6
    elif pnl_r > -0.5:
        rr = 4
    elif pnl_r >= -1.05:
        rr = 3
    else:
        rr = 0

    discipline = 10 if dissents == 0 else 6

    if outcome in ("tp", "tp_after_partial", "trailing_stop") and pnl_r > 0:
        management = 10
    elif outcome == "be_after_partial":
        management = 8
    elif outcome in ("timeout", "end_of_data") and pnl_r > 0:
        management = 6
    elif outcome == "sl":
        management = 4
    else:
        management = 3

    efficiency = 5
    if mfe_r > 0.1:
        capture = pnl_r / mfe_r
        efficiency = 10 if capture >= 0.7 else 8 if capture >= 0.5 else 5 if capture >= 0.2 else 2

    total = entry + sl_score + rr + discipline + management + efficiency
    detail = (
        f"Entry {entry}, SL {sl_score}, RR {rr}, วินัย {discipline}, "
        f"จัดการ {management}, ประสิทธิภาพ {efficiency}"
    )
    return total, detail


def aggregate_review(trades: list) -> dict:
    """สรุปภาพรวม + คำแนะนำเชิงระบบจากไม้ทั้งหมดของ run — ใช้ตอบว่าควรปรับอะไร"""
    if not trades:
        return {"total": 0, "recommendations": ["ยังไม่มีไม้ให้วิเคราะห์"]}

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    def _avg(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    # แพ้ทั้งที่เคยกำไร ≥1R — กลุ่มที่ partial TP + BE กู้ได้
    losses_were_winning = [t for t in losses if t.mfe_r >= 1.0]
    # แพ้แบบผิดทางทันที — ปัญหาเงื่อนไขเข้า
    losses_wrong_entry = [t for t in losses if t.mfe_r < 0.3]
    # ชนะแบบราคาแทบไม่ย้อน — SL แคบลงได้
    wins_clean = [t for t in wins if t.mae_r <= 0.3]
    # ชนะแบบเฉียดตาย
    wins_near_death = [t for t in wins if t.mae_r >= 0.8]
    # ชน TP แล้วราคาวิ่งต่อ ≥1R — TP ต่ำไป / น่าทำ snowball
    tp_hits = [t for t in trades if t.outcome in ("tp", "tp_after_partial") and t.post_exit_r is not None]
    tp_ran_on = [t for t in tp_hits if t.post_exit_r >= 1.0]

    stats = {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "avg_win_r": round(_avg([t.pnl_r for t in wins]), 2),
        "avg_loss_r": round(_avg([t.pnl_r for t in losses]), 2),
        "avg_mae_r_wins": round(_avg([t.mae_r for t in wins]), 2),
        "avg_mfe_r_losses": round(_avg([t.mfe_r for t in losses]), 2),
        "losses_were_winning_1r": len(losses_were_winning),
        "losses_wrong_entry": len(losses_wrong_entry),
        "wins_clean_sl": len(wins_clean),
        "wins_near_death": len(wins_near_death),
        "tp_hits_with_lookahead": len(tp_hits),
        "tp_ran_on_1r": len(tp_ran_on),
    }

    recs: list[str] = []
    if losses and len(losses_were_winning) / len(losses) >= 0.25:
        recs.append(
            f"ควรเปิด partial TP: {len(losses_were_winning)}/{len(losses)} ไม้ที่แพ้ เคยกำไรเกิน +1R มาก่อน "
            "— เก็บครึ่งไม้ที่ 1R แล้วเลื่อน SL ไป BE จะเปลี่ยนไม้กลุ่มนี้จากแพ้เต็มเป็นเสมอ/กำไรเล็ก"
        )
    if losses and len(losses_wrong_entry) / len(losses) >= 0.5:
        recs.append(
            f"เงื่อนไขเข้ายังอ่อน: {len(losses_wrong_entry)}/{len(losses)} ไม้ที่แพ้ ผิดทางแทบทันที (MFE < 0.3R) "
            "— แก้ที่ตัวกรองสัญญาณ/กรรมการ ไม่ใช่ที่ SL/TP"
        )
    if wins and len(wins_clean) / len(wins) >= 0.5:
        recs.append(
            f"SL กว้างเกินจำเป็น: {len(wins_clean)}/{len(wins)} ไม้ที่ชนะ ราคาแทบไม่ย้อน (MAE ≤ 0.3R) "
            "— ลดระยะ SL ลงได้ จะเปิด lot ใหญ่ขึ้นที่ความเสี่ยงเท่าเดิม (R:R ดีขึ้นอัตโนมัติ)"
        )
    if wins and len(wins_near_death) / len(wins) >= 0.3:
        recs.append(
            f"SL แคบเกิน: {len(wins_near_death)}/{len(wins)} ไม้ที่ชนะ เคยสวนลึกเกิน -0.8R ก่อนกลับมาชนะ "
            "— ถ้าตลาด noise ขึ้นอีกนิด ไม้พวกนี้จะกลายเป็นแพ้หมด ควรขยาย SL"
        )
    if tp_hits and len(tp_ran_on) / len(tp_hits) >= 0.4:
        recs.append(
            f"เข้าทาง snowball: {len(tp_ran_on)}/{len(tp_hits)} ไม้ที่ชน TP ราคายังวิ่งต่อ ≥1R หลังปิด "
            "— TP ปัจจุบันทิ้งกำไรไว้บนโต๊ะ น่าลอง trailing stop หรือถือ runner ครึ่งไม้"
        )
    elif tp_hits and len(tp_ran_on) / len(tp_hits) <= 0.15:
        recs.append(
            f"ไม่ต้อง snowball: มีแค่ {len(tp_ran_on)}/{len(tp_hits)} ไม้ที่ราคาวิ่งต่อหลังชน TP "
            "— TP ปัจจุบันเก็บได้เกือบสุดทางแล้ว การถือต่อจะโดนย้อนมากกว่าได้เพิ่ม"
        )
    if not recs:
        recs.append("ยังไม่พบจุดปรับที่ชัดจากข้อมูลชุดนี้ — เก็บไม้เพิ่มก่อนสรุป")

    stats["recommendations"] = recs
    return stats


def aggregate_review_from_rows(rows: list[dict]) -> dict:
    """เวอร์ชันรับ dict (จาก DB) แทน Trade object — ใช้ฝั่ง API/dashboard"""

    class _Row:
        def __init__(self, d: dict):
            self.pnl = d.get("pnl") or 0.0
            self.pnl_r = d.get("pnl_r") or 0.0
            self.mae_r = d.get("mae_r") or 0.0
            self.mfe_r = d.get("mfe_r") or 0.0
            self.post_exit_r = d.get("post_exit_r")
            self.outcome = d.get("outcome") or ""

    usable = [r for r in rows if r.get("pnl_r") is not None]
    return aggregate_review([_Row(r) for r in usable])
