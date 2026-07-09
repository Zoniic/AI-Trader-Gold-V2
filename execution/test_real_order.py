"""ทดสอบยิง order จริงเข้า MT5 demo ตรงๆ (ไม่รอสัญญาณจากกลยุทธ์) — พิสูจน์ pipeline จบครบวงจร

เปิดไม้เล็กสุด (min_lot) 1 ไม้ ด้วย SL/TP ห่างเพียงพอไม่ให้โดนก่อนปิดเอง แล้วปิดทันทีหลังยืนยันว่าเปิดสำเร็จ
มี _assert_demo() ป้องกันอยู่แล้วใน broker.py — ยิงบัญชีจริงไม่ได้แม้ตั้งใจ

ใช้งาน: python -m execution.test_real_order
"""
from __future__ import annotations

import time

from config import load_settings
from core.signal import Direction
from execution.broker import MT5Broker, NotDemoAccountError


def main() -> None:
    settings = load_settings()
    broker = MT5Broker(dry_run=False)  # ยิงจริง — แต่ _assert_demo() กันบัญชีจริงไว้แล้ว

    login = settings.mt5.login
    if login is not None:
        broker.connect(login, settings.mt5.password, settings.mt5.server)
    else:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            raise ConnectionError(f"เชื่อมต่อ MT5 ไม่สำเร็จ: {mt5.last_error()}")
        broker._mt5 = mt5
        broker._connected = True
        broker._assert_demo()

    info = broker._mt5.account_info()
    print(f"[test] เชื่อมต่อสำเร็จ: login={info.login} server={info.server} balance={info.balance} "
          f"trade_mode={info.trade_mode} (0=DEMO)")

    symbol = settings.symbol
    tick = broker._mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"ดึงราคาปัจจุบันของ {symbol} ไม่ได้ — เช็คว่า symbol ถูกต้องและตลาดเปิดอยู่")

    price = tick.ask
    # SL/TP ห่างพอที่จะไม่โดนก่อนที่เราจะปิดเอง (fixed points ห่างจากราคา ณ ตอนนี้)
    point = broker._mt5.symbol_info(symbol).point
    sl_distance = 500 * point  # ระยะห่างกันพลาด (XAUUSD point เล็ก ต้องเผื่อเยอะ)
    sl = price - sl_distance
    tp = price + sl_distance * 3

    print(f"[test] จะยิง BUY 0.01 lot {symbol} @ {price:.2f} sl={sl:.2f} tp={tp:.2f}")
    result = broker.send_order(symbol, Direction.BUY, 0.01, sl, tp)
    print(f"[test] ผลส่งออเดอร์: success={result.success} ticket={result.ticket} message={result.message}")

    if not result.success:
        print("[test] ล้มเหลว — ไม่มีไม้ให้ปิด จบการทดสอบ")
        broker.disconnect()
        return

    print("[test] รอ 3 วิ แล้วเช็คว่า position เปิดจริงไหม...")
    time.sleep(3)
    pos = broker.get_position(result.ticket)
    if pos is None:
        print("[test] ⚠ หา position ไม่เจอ (อาจปิดไปแล้วเองจาก SL/TP หรือ ticket ไม่ตรง)")
    else:
        print(f"[test] ✅ ยืนยัน position เปิดจริงใน MT5: ticket={pos.ticket} volume={pos.volume} "
              f"price_open={pos.price_open} profit={pos.profit}")

        print("[test] ปิดไม้ทันที...")
        close_result = broker.close_position(symbol, result.ticket)
        print(f"[test] ผลปิดไม้: success={close_result.success} message={close_result.message}")

        time.sleep(2)
        pnl = broker.get_closed_deal_pnl(result.ticket)
        print(f"[test] pnl จริงจาก deal history: {pnl}")

    broker.disconnect()
    print("[test] จบการทดสอบ — ตัดการเชื่อมต่อแล้ว")


if __name__ == "__main__":
    try:
        main()
    except NotDemoAccountError as e:
        print(f"[test] BLOCKED: {e}")
