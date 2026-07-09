# AI Trader V2 — โครงเรียบง่ายสำหรับเทรดบอท XAUUSD

เวอร์ชันนี้เริ่มใหม่แบบเรียบง่าย: กลยุทธ์เดียว (EMA crossover) + backtest engine เดียว
เป้าหมายเฟสนี้คือพิสูจน์ว่าท่อ (pipeline) ทำงานครบวงจร ไม่ได้เน้นหา alpha
(ดูโปรเจกต์ `AI Trader` (V1) ที่โฟลเดอร์ข้างๆ ถ้าต้องการอ้างอิงแนวคิด 13 กลยุทธ์/league/walk-forward)

## โครงสร้างโปรเจกต์

```
config.py            ตั้งค่าทั้งหมด (อ่านจาก .env)
core/                 สัญญาข้อมูล: Signal, MarketData, Strategy base class + registry
strategies/           กลยุทธ์ — ตอนนี้มี ema_cross.py ตัวเดียว
risk/                 คำนวณขนาดล็อต + drawdown guard (ใช้เดี่ยวได้ ไม่ผูกกับที่อื่น)
backtest/             engine จำลองเทรด, cost model, metrics, walk-forward (out-of-sample check)
data/                 โหลดราคา: parquet/csv ในเครื่อง หรือดึงสดจาก MT5
persistence/          SQLite log ทุก signal/decision/trade (ตามรอยย้อนกลับได้)
execution/            broker.py — ชั้นยิงออเดอร์ MT5 (สแคฟโฟลดิ้ง ยังไม่ถูกเรียกใช้จริงที่ไหน)
reporting/            สรุปผล + เซฟ trades.csv + equity_curve.png + walk-forward report
tests/                pytest — เน้นจุดเสี่ยง (demo guard, no-lookahead, logging)
data_files/           วางไฟล์ราคาที่นี่ (gitignored)
reports/              ผลรันแต่ละครั้ง (gitignored)
trading_log.db        SQLite log สะสมทุกรัน (gitignored)
dashboard.py          Streamlit dashboard อ่านผลจาก trading_log.db
web/                  ทางเลือกที่ 2: FastAPI + Next.js dashboard เปิดผ่าน LAN ได้ (ดู web/README.md)
run_backtest.py       entrypoint หลัก — รัน backtest ครั้งเดียว
run_walkforward.py    entrypoint ตรวจความสม่ำเสมอนอกช่วงข้อมูล
```

ยังไม่มี: live runner ที่เรียก execution/broker.py จริง, regime detection, multi-strategy
league — ตั้งใจตัดออกเพื่อให้ง่ายก่อน จะเพิ่มทีหลังเมื่อจำเป็นจริง

## ติดตั้ง

```bash
pip install -r requirements.txt
copy .env.example .env   # แล้วแก้ค่าตามจริง (ไม่บังคับถ้าจะใช้ไฟล์ CSV ในเครื่อง)
```

## การได้มาซึ่งข้อมูล (เลือกทางใดทางหนึ่ง)

1. **มี MT5 ติดตั้งในเครื่องนี้:** ใส่ `MT5_LOGIN`/`MT5_PASSWORD`/`MT5_SERVER` ใน `.env` แล้วรัน
   ```bash
   python -m data.mt5_loader
   ```
   จะดึงราคาตาม `SYMBOL`/`TIMEFRAME`/`START_DATE`/`END_DATE` ใน `.env` แล้วเซฟเป็น
   `data_files/XAUUSD_H1.parquet`

2. **ไม่มี MT5 ในเครื่องนี้:** วางไฟล์ CSV เองที่ `data_files/XAUUSD_H1.csv`
   ต้องมีคอลัมน์: `time, open, high, low, close, volume`

`run_backtest.py` จะเลือกใช้ parquet ก่อน ถ้าไม่มีค่อยหา csv ถ้าไม่มีอีกค่อยลองดึงสดจาก MT5

## รัน backtest

```bash
python run_backtest.py
```

จะพิมพ์สรุปผล (win rate, profit factor, max drawdown, expectancy) และเซฟไฟล์ไว้ที่
`reports/ema_cross_<timestamp>/` (trades.csv, equity_curve.png, summary.txt)

ทุก signal/decision/trade ของรันนี้ยังถูกบันทึกลง `trading_log.db` (SQLite) ด้วย — ดูหัวข้อ
"บันทึกย้อนหลัง" ด้านล่าง

## ตรวจความสม่ำเสมอนอกช่วงข้อมูล (walk-forward)

`run_backtest.py` บอกแค่ว่า "ภาพรวมกำไรหรือขาดทุน" แต่ไม่บอกว่าเป็นเพราะช่วงเวลาหนึ่งที่โชคดี
หรือ edge จริง ให้รัน:

```bash
python run_walkforward.py
```

จะแบ่งข้อมูลเป็น 5 ช่วงต่อเนื่อง รัน backtest อิสระในแต่ละช่วง แล้วเช็คว่า expectancy เป็นบวก
สม่ำเสมอกี่ช่วง (fold) — ถ้าช่วงส่วนใหญ่มีเทรดน้อยกว่าเกณฑ์ (`min_trades_per_fold` ในโค้ด) จะขึ้น
"ข้อมูลไม่พอสรุป" แทนที่จะฟันธงเดา หมายเหตุ: นี่คือการเช็ค "สม่ำเสมอข้ามช่วงเวลา" ไม่ใช่
walk-forward แบบ train/refit พารามิเตอร์ตามตำรา เพราะกลยุทธ์ปัจจุบันยังไม่มีพารามิเตอร์ให้ปรับ

ผลเซฟไว้ที่ `reports/walkforward_ema_cross_<timestamp>/` (folds.csv, summary.txt)

### ⚠ ข้อควรระวัง: kill-switch ทำให้ total pnl ของ run_backtest.py ตีความผิดได้ง่าย

`run_backtest.py` รันต่อเนื่องยาวด้วยบาลานซ์เดียว ถ้า drawdown ชนเพดาน `MAX_DRAWDOWN_PCT`
เมื่อไหร่ **จะหยุดเทรดถาวรตลอดที่เหลือของการรัน** (ไม่กลับมาเทรดใหม่แม้ราคาจะฟื้น) — โค้ดจะ
พิมพ์ `[engine] kill-switch ทำงาน...` และ `⚠ หยุดเทรดก่อนหมดข้อมูล` เตือนไว้ชัดเจนถ้าเกิดเหตุการณ์นี้
ให้เช็คบรรทัดนี้ทุกครั้งก่อนสรุปผล — ถ้าเจอ ตัวเลข total_pnl ที่เห็นคือผลแค่ "ก่อนชนกำแพง" เท่านั้น
ให้ดู `run_walkforward.py` ประกอบเพื่อดูว่าช่วงหลังจากจุดที่หยุดเป็นยังไงจริง ๆ

## บันทึกย้อนหลัง (persistence/db.py)

ทุกครั้งที่รัน `run_backtest.py` จะมีการบันทึกลง `trading_log.db` (ไฟล์เดียว สะสมทุกรัน แยกด้วย
`run_id`) 5 ตาราง:

- `runs` — ข้อมูลระดับรัน 1 แถวต่อ 1 ครั้งที่รัน (กลยุทธ์, บาลานซ์เริ่ม/จบ, win rate, profit factor,
  max drawdown, expectancy, จุดที่ kill-switch ทำงานถ้ามี) — ใช้เทียบผลระหว่างรันย้อนหลังได้
- `signals` — สัญญาณดิบทุกอันจาก strategy
- `decisions` — อนุมัติหรือปฏิเสธ (พร้อมเหตุผลจาก risk guard) อ้างอิงกลับไปที่ signal
- `trades` — เทรดที่เปิดจริงและผลตอนปิด อ้างอิงกลับไปที่ signal
- `orders` — ไว้สำหรับ execution layer ในอนาคต (ยังไม่มีการเขียนแถวนี้ตอนนี้เพราะยังไม่ยิงออเดอร์จริง)

query ตัวอย่าง: `sqlite3 trading_log.db "select * from decisions where approved=0 limit 10;"`
เพื่อดูว่า signal ไหนถูกปฏิเสธเพราะอะไรบ้าง — ไฟล์นี้คือที่เดียวที่ควรอ้างอิงตอนจะย้อนกลับมาวิเคราะห์
ว่ากลยุทธ์ไหนควรปรับตรงไหน (ใช้ query helper ใน `persistence/db.py`: `list_runs()`, `get_trades()`,
`get_decisions()`, `get_signals()` แทนการเขียน SQL เองก็ได้)

## Dashboard

มี 2 ทางเลือก ใช้ DB (`trading_log.db`) เดียวกัน เลือกอันไหนก็ได้ไม่ชนกัน:

1. **dashboard.py (Streamlit)** — เร็ว ไฟล์เดียว ดูคนเดียวในเครื่องนี้พอ (หัวข้อด้านล่าง)
2. **[web/](web/README.md) (FastAPI + Next.js)** — UI ปรับแต่งเองได้เต็มที่ เปิดให้คนอื่นในวง LAN
   เดียวกันเข้าดูผ่านเบราว์เซอร์ได้ มีระบบรหัสผ่านกันคนนอก — ดูวิธีรันที่ [web/README.md](web/README.md)

### dashboard.py (Streamlit)

```bash
streamlit run dashboard.py
```

เปิดเบราว์เซอร์ไปที่ `http://localhost:8501` จะเห็น:

- เลือกดูผลแต่ละ run ย้อนหลังได้จาก dropdown (อ่านจากตาราง `runs`)
- เมตริกสรุป (เทรดทั้งหมด, win rate, profit factor, max drawdown, expectancy, balance)
- แจ้งเตือนทันทีถ้า run นั้นโดน kill-switch ตัดจบก่อนหมดข้อมูล
- Equity curve + ตารางรายการเทรดทั้งหมด
- สรุปสัญญาณที่ถูกปฏิเสธ แยกตามเหตุผล (ช่วยเห็นว่า risk guard บล็อกอะไรบ่อยที่สุด)

**เรื่อง "realtime":** แดชบอร์ดนี้ auto-refresh ทุก 5 วินาที (ปิดได้จาก checkbox ในแถบด้านซ้าย)
เพื่อดึงข้อมูลล่าสุดจาก `trading_log.db` มาแสดงเสมอ — แต่ตอนนี้ข้อมูลจะขยับก็ต่อเมื่อมีคนรัน
`run_backtest.py`/`run_walkforward.py` ใหม่ เพราะยังไม่มี live runner ที่เทรดต่อเนื่องอัตโนมัติ
(ดูหัวข้อถัดไป) วันที่มี live runner จริงและเขียนลง DB เดียวกันนี้ แดชบอร์ดจะเห็นข้อมูลสดทันที
โดยไม่ต้องแก้โค้ดแดชบอร์ดเลย

## execution/broker.py — ยังไม่ได้ต่อใช้งานจริง

มี `MT5Broker` ให้แล้วสำหรับตอนพร้อมจะยิงออเดอร์ (`connect()`, `send_order()`, `close_position()`)
แต่ **ไม่มีโค้ดที่ไหนเรียกมันโดยอัตโนมัติ** — ต้อง import แล้วเรียกเองเท่านั้น เพื่อความปลอดภัย:

- `connect()` เช็ค `account_info().trade_mode` ทันที ถ้าไม่ใช่บัญชี demo จะ raise `NotDemoAccountError`
  และตัดการเชื่อมต่อทันที
- `send_order()`/`close_position()` เช็คซ้ำทุกครั้งก่อนยิง (เผื่อสลับบัญชีระหว่างรัน)
- ค่าเริ่มต้น `dry_run=True` เสมอ — แค่พิมพ์ว่าจะยิงอะไร ไม่ยิงจริงแม้เป็นบัญชี demo ก็ตาม
  ต้องตั้งใจส่ง `dry_run=False` เองถึงจะยิงจริง

## รันเทสต์

```bash
pytest tests/ -v
```

เทสต์เน้นจุดเสี่ยงจริง ไม่ใช่ coverage ทุกบรรทัด: strategy ไม่มองอนาคต (no-lookahead), broker
ปฏิเสธบัญชีที่ไม่ใช่ demo, logger บันทึกครบทุก signal/decision/trade, risk sizing คำนวณถูกสัดส่วน

## ทีม (กลยุทธ์) ที่มีตอนนี้ — 10 ทีมแข่งขันกัน

ทุกทีมมี **นักเทรด 5 คน** (1 เสนอ setup + 4 review คนละด้าน) โหวตก่อนเข้าไม้ทุกครั้ง
ค้านได้ไม่เกิน 1 เสียงถึงเข้าจริง — ความเห็นทุกคนบันทึกลง DB ดูย้อนหลังได้บน dashboard

| ทีม | สำนัก/แรงบันดาลใจ |
|---|---|
| `ema_cross` | Trend-following (EMA crossover คลาสสิก) |
| `mean_reversion` | BB+RSI counter-trend (แนว Linda Raschke) |
| `donchian_breakout` | Turtle Traders (Richard Dennis) |
| `london_breakout` | Session breakout (intraday FX/gold) |
| `macd_momentum` | MACD (Gerald Appel) |
| `rsi_divergence` | Divergence reversal (ต่อยอด Wilder) |
| `vwap_reversion` | VWAP fade (โต๊ะเทรดสถาบัน) |
| `trend_pullback` | Pullback continuation (Minervini/O'Neil) |
| `volatility_breakout` | Range expansion (Larry Williams) |
| `sr_bounce` | S/R bounce (price action ล้วน) |

รันทีมไหนก็ได้ด้วย `--strategy` แล้วผลจะขึ้นตารางแข่งขัน (league) บน dashboard อัตโนมัติ:
```bash
python run_backtest.py --strategy london_breakout
python run_walkforward.py --strategy london_breakout
```

ทุก backtest จะแยกผลตามสภาวะตลาด (trend/range/volatile) ให้อัตโนมัติ — ดูได้ทั้งบน console,
`reports/<team>_<timestamp>/regime_breakdown.csv`, และในทั้งสอง dashboard

## Config ต่อทีม + ระบบวิเคราะห์ไม้อัตโนมัติ

- **configs/<team>.json** — setting ของแต่ละทีม (พารามิเตอร์กลยุทธ์ + trade management)
  สร้างอัตโนมัติครั้งแรก แก้ไฟล์แล้วรันใหม่ได้เลย **ทุก run บันทึก config snapshot ลง DB**
  (คอลัมน์ `runs.config`) — เปิดดูบน dashboard ได้ว่าผลไหนมาจาก setting ไหน
- **Trade management**: ตั้ง `partial_tp_r` (เช่น 1.0 = ปิดครึ่งไม้เมื่อกำไรถึง 1R แล้วเลื่อน
  SL ไป breakeven) ใน config ของทีมนั้นได้เลย
- **ทุกไม้ถูกรีวิวอัตโนมัติ** ด้วย MAE/MFE (ราคาสวนลึกสุด/เป็นใจไกลสุดระหว่างถือ):
  แพ้เพราะผิดทางทันทีหรือเคยกำไรแล้วหลุดมือ? SL แคบ/กว้างไป? TP ทิ้งกำไรบนโต๊ะไหม
  (`post_exit_r` — ควร snowball/trailing ไหม)? — สรุปเป็นคำแนะนำท้ายรันและบน dashboard

## แผนที่ "กราฟแบบไหน ใช้ทีมไหนเทรด"

Dashboard มี section 🗺️ สรุปจากผลรันล่าสุดของแต่ละ (ทีม, timeframe) ว่าใน trend/range/volatile
ทีมไหนทำกำไรสูงสุด (มี guard ขั้นต่ำ 15 ไม้/ช่อง — ช่องที่ sample ไม่พอจะไม่ฟันธง)
คำนวณด้วย `backtest/regime_league.py` ผ่าน endpoint `/regime-champions`

## Trade management ต่อทีม (partial TP / trailing / snowball)

ตั้งใน `configs/<team>.json` (หรือ `configs/<team>_<TF>.json` เพื่อ override เฉพาะ timeframe):
- `partial_tp_r`: ปิดบางส่วนเมื่อกำไรถึง X R แล้วเลื่อน SL ไป breakeven
- `trailing_stop_r` + `trailing_activate_r`: ลาก SL ตามหลังจุดสูงสุด
- `remove_tp_when_trailing: true`: ตัด TP ทิ้งเมื่อ trailing ทำงาน = snowball เต็มรูปแบบ

บทเรียนจากการทดลองจริง (london_breakout H1): partial 1R = แย่ลงมาก, trailing 1R เพียว = แย่ลง,
**runner (เก็บครึ่งที่ 2R + trail ที่เหลือ 1.5R) = ดีขึ้น 39%** — ให้ข้อมูลตัดสิน อย่าเดา

## เปลี่ยน timeframe (เร็ว/ช้ากว่า 1H)

ตั้ง `TIMEFRAME` ใน `.env` (M5/M15/M30/H1/H4/D1) แล้วดึงข้อมูลใหม่:
```bash
TIMEFRAME=M15 START_DATE=2025-07-01 python -m data.mt5_loader   # โบรกให้ TF เล็กย้อนหลังสั้นกว่า H1
TIMEFRAME=M15 python run_backtest.py --strategy london_breakout
```
ข้อควรระวัง TF เล็ก: ระยะ SL/TP หดตาม ATR แต่สเปรดเท่าเดิม → ต้นทุนกินสัดส่วนกำไรมากขึ้น
สัญญาณถี่ขึ้นแต่ noise มากขึ้นด้วย — league บน dashboard มีคอลัมน์ TF ให้แยกเปรียบเทียบ

## วิธีเพิ่มกลยุทธ์ใหม่ (ทีมถัดไป)

1. สร้างไฟล์ใหม่ใน `strategies/` เช่น `strategies/breakout.py`
2. ทำ class inherit จาก `core.strategy.Strategy` คืนค่าเป็น `core.signal.Signal`
3. แปะ decorator `@register_strategy` ไว้บน class
4. เพิ่ม `from . import breakout` ใน `strategies/__init__.py`
5. รันทันทีด้วย `python run_backtest.py --strategy breakout` — ไม่ต้องแก้โค้ดที่อื่นเลย

## กฎเหล็ก (ยึดตาม V1)

ห้ามเขียนโค้ดยิงออเดอร์จริงหรือ demo จนกว่าจะผ่านลำดับนี้ครบ:

**ข้อมูลจริง → backtest ที่หักต้นทุนแล้วให้ผลบวกสม่ำเสมอ → demo → forward test อย่างน้อย 2-4 สัปดาห์**

เฟสนี้ของโค้ด (V2 ตอนนี้) มี `execution/broker.py` เป็นสแคฟโฟลดิ้งพร้อมด่านความปลอดภัยแล้ว
(ดูหัวข้อด้านบน) แต่ **ยังไม่มี live runner ใดเรียกใช้มันจริง** — จะเริ่มเรียกใช้ได้ก็ต่อเมื่อผ่าน
ข้อมูลจริง → backtest ที่หักต้นทุนแล้วให้ผลบวกสม่ำเสมอ → walk-forward ผ่าน → ทดสอบ
`dry_run=True` บนบัญชี demo จริงก่อน แล้วค่อยเปิด `dry_run=False` บนบัญชี demo เท่านั้น
ห้ามข้ามขั้นตอนไหนไปเด็ดขาด
