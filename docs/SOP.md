# SOP (Standard Operating Procedure) — ทุกทีมยึดเอกสารเดียวกัน

เอกสารนี้คือ "กฎกลาง" ที่ทุกทีม (บอท) ต้องทำตามเหมือนกันหมด ต่างกันแค่ตัวเลข
(risk %, allowed_regimes, พารามิเตอร์) ซึ่งกำหนดแยกไว้ใน `configs/<team>.json`

## 1. ขั้นตอนก่อนตลาดเปิด (ทุกเช้า)
1. เช็ค `docs/NEWS_CALENDAR.md` หรือปฏิทินข่าวจริงของวันนั้น (ยังไม่ automate — ดูข้อ 15)
2. รัน `python run_analysis.py` ดูว่าสภานักวิเคราะห์เจออะไรผิดปกติจากรอบก่อนไหม
3. ตรวจว่า `trading_log.db` ไม่มี run ค้าง (finished_at ว่าง) จากรอบก่อน

## 2. Checklist ก่อนเข้าไม้ (บังคับทุกไม้ ทุกทีม)
ทีมจะเข้าไม้ได้ต่อเมื่อผ่านครบทุกข้อ (คณะกรรมการ 5 คนในโค้ดคือการบังคับ checklist นี้อัตโนมัติ):

| ข้อ | เช็คอะไร | ใครคุมในโค้ด |
|---|---|---|
| Trend/สภาวะตลาด | ตรงกับ `allowed_regimes` ของทีมไหม | regime gate ใน engine |
| Setup ตรงเงื่อนไข | indicator ของกลยุทธ์ยืนยันไหม | `strategy.evaluate()` |
| ความเสี่ยง (Risk officer) | R:R ผ่านเกณฑ์ขั้นต่ำของทีมไหม | `make_risk_officer` |
| ช่วงเวลา (Session) | ไม่ใช่ชั่วโมง rollover/สภาพคล่องต่ำ | `make_session_analyst` |
| ความผันผวน | ATR ไม่พุ่งผิดปกติ (เว้นทีมที่ต้องการ) | `make_volatility_analyst` |
| SL | ระยะ SL มากกว่า 0 และสมเหตุสมผล | `make_risk_officer` |
| TP | ตั้งตาม logic ของทีม (ATR/mid-band/channel) | strategy เอง |
| มติทีม | อนุมัติ >= `min_approvals` (ปกติ 4/5) | `Committee.review()` |

ครบทุกข้อค่อยเข้า — ไม่มีข้อยกเว้น

## 3. ขั้นตอนระหว่างถือสถานะ
- Trade management ต่อไม้ตาม `configs/<team>.json` (`partial_tp_r`, `trailing_stop_r`) ทำงานอัตโนมัติทุกแท่ง
- ห้ามแทรกแซงไม้ที่เปิดอยู่ด้วยมือ (บอทตัดสินใจตามกฎที่ตั้งไว้ล่วงหน้าเท่านั้น — กัน emotional override)

## 4. ขั้นตอนปิดสถานะ
- ปิดตาม SL/TP/trailing/timeout ที่ engine คำนวณ (`backtest/engine.py::_simulate_trade`)
- ทุกไม้บันทึก MAE/MFE/pnl_r/outcome ลง DB ทันที (`persistence/db.py::log_trade`)

## 5. ขั้นตอนบันทึกผล (Trading Journal อัตโนมัติ)
ทุกไม้บันทึกอัตโนมัติครบตามที่ต้องการ:

| ต้องการ | เก็บที่ไหน |
|---|---|
| เหตุผลเข้า | `signals.reason` + `signals.discussion` (มติกรรมการ 5 คน) |
| เหตุผลออก | `trades.outcome` + `trades.review` (บทวิเคราะห์อัตโนมัติ) |
| Timeframe | `runs.timeframe` |
| RR | `trades.pnl_r`, `trades.mae_r`, `trades.mfe_r` |
| Scorecard | ฝังท้าย `trades.review` ("คะแนนไม้ X/60") |
| Emotion | บอทไม่มีอารมณ์ — แต่ `analysis/council.py` (Psychology Analyst) ตรวจ "รูปแบบ" ที่คล้ายพฤติกรรมมนุษย์ผิดพลาด (revenge trade) แทน |

**เรื่อง Screenshot (SOP ข้อ 7):** ระบบนี้เป็น backtest ไม่มีหน้าจอเทรดสดให้แคป — เทียบเท่าคือกราฟ
equity curve (`reports/*/equity_curve.png`) ที่เซฟทุกรัน เมื่อขึ้น live runner จริงในอนาคต
ควรเพิ่มการแคปหน้าจอ MT5 ก่อน/หลังเข้า-ออกจริง

## 6. ขั้นตอนสรุปหลังตลาดปิด / ประชุมประจำสัปดาห์
รัน `python run_analysis.py` — สภานักวิเคราะห์ 4 คน (Risk / Edge / Discipline / Psychology)
สรุปสิ่งที่เจอจากข้อมูลจริงของรอบล่าสุด แทนการประชุมคนจริง เตรียมขยายเป็น LLM agent จริงได้
(ดู `analysis/council.py` — ออกแบบ interface ไว้ให้สลับจากกฎเป็น LLM ได้โดยไม่กระทบส่วนอื่น)

## 7. Post-Mortem เมื่อขาดทุนหนัก/ละเมิดกฎ
เมื่อทีมใดโดน kill-switch (drawdown 20%) หรือ daily/weekly loss lock ทำงาน ให้ตอบ 4 คำถามนี้
ก่อนแก้ config (บันทึกคำตอบไว้ใน `notes` ของ config ไฟล์นั้นเสมอ):
1. เกิดอะไรขึ้น — ดู `trades.review` ของไม้ก่อนเกิดเหตุ + `runs.halt_reason`
2. สาเหตุคืออะไร — เงื่อนไขเข้าอ่อน (ดู mfe_r ต่ำ) หรือ SL/TP ผิดสัดส่วน (ดู mae_r)?
3. ป้องกันไม่ให้เกิดอีกยังไง — ปรับ `allowed_regimes` / `min_approvals` / risk% / trade_management
4. ต้องปรับกฎ SOP นี้ไหม — ถ้าเจอรูปแบบใหม่ที่ checklist ข้อ 2 ไม่ครอบคลุม ให้เพิ่ม committee member ใหม่

## 8. หลักคิดสูงสุด (SOP ข้อ 30)
> "รักษาทุน" มาก่อน "ทำกำไร" — ระบบนี้ออกแบบให้ **kill-switch/loss-lock ทำงานก่อนเสมอ**
> ไม่ว่าทีมจะดูมีโอกาสทำกำไรมากแค่ไหน เป้าหมายคือ**อยู่รอดระยะยาว**ให้ edge ที่พิสูจน์แล้ว
> (walk-forward ผ่าน) สะสมผลตอบแทนไปเรื่อยๆ ไม่ใช่เร่งผลตอบแทนรายเดือนจนเสี่ยงเจ๊ง —
> ดูตัวเลขจริงได้จาก `python run_portfolio.py` ว่า risk multiplier แต่ละระดับ แลกกับ
> โอกาสเจ๊งเท่าไหร่

## Portfolio Thinking (SOP ข้อ 25)
`portfolio/simulate.py` บังคับ 3 กติกาไม่ให้ทุกทีม "กองความเสี่ยงรวม" โดยไม่ตั้งใจ:
- จำกัดไม้เปิดพร้อมกันทั้งพอร์ต (`max_concurrent`)
- จำกัดจำนวนไม้ทิศทางเดียวกันพร้อมกัน (`max_same_direction`) — กันทุกทีม BUY/SELL พร้อมกันหมด
- ล็อกการเทรดเมื่อขาดทุนรวมทั้งพอร์ตถึงลิมิตรายวัน (`daily_loss_limit_pct`)
