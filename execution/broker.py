"""ชั้นยิงออเดอร์ผ่าน MT5 — สแคฟโฟลดิ้งไว้ก่อน ยังไม่มี live_runner ที่เรียกใช้จริง

กฎเหล็ก (ยึดตาม V1 CLAUDE.md): ห้ามยิงออเดอร์เข้าบัญชีจริงเด็ดขาด
- connect() เช็ค account_info().trade_mode ทันที ถ้าไม่ใช่ demo จะ raise + ตัดการเชื่อมต่อ
- send_order()/close_position() เช็คซ้ำทุกครั้งก่อนยิง (เผื่อมีคนสลับบัญชีระหว่างรันอยู่)
- dry_run=True เป็นค่าเริ่มต้นเสมอ ต้องตั้งใจส่ง dry_run=False เองเท่านั้นถึงจะยิงจริง (แม้เป็น demo)

โมดูลนี้ไม่ได้ถูกเรียกจาก run_backtest.py หรือที่อื่นใดอัตโนมัติ — import แล้วเรียกเองเท่านั้น
"""
from __future__ import annotations

from dataclasses import dataclass

from core.signal import Direction


class NotDemoAccountError(Exception):
    """บัญชีที่เชื่อมต่อไม่ใช่ demo — ปฏิเสธการเชื่อมต่อ/การยิงออเดอร์ทันที"""


@dataclass
class OrderResult:
    success: bool
    ticket: int | None = None
    message: str = ""


class MT5Broker:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self._mt5 = None
        self._connected = False

    def connect(self, login: int, password: str, server: str) -> bool:
        import MetaTrader5 as mt5

        self._mt5 = mt5
        if not mt5.initialize(login=login, password=password, server=server):
            raise ConnectionError(f"เชื่อมต่อ MT5 ไม่สำเร็จ: {mt5.last_error()}")

        try:
            self._assert_demo()
        except NotDemoAccountError:
            mt5.shutdown()
            raise

        self._connected = True
        return True

    def _assert_demo(self) -> None:
        info = self._mt5.account_info()
        if info is None:
            raise ConnectionError("อ่าน account_info ไม่ได้ — เช็คการเชื่อมต่อ MT5")
        if info.trade_mode != self._mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise NotDemoAccountError(
                f"บัญชี login={info.login} ไม่ใช่บัญชี demo (trade_mode={info.trade_mode}) "
                "— กฎเหล็กห้ามยิงออเดอร์บัญชีจริง ปฏิเสธการทำงาน"
            )

    def send_order(
        self, symbol: str, direction: Direction, lot: float, sl: float, tp: float
    ) -> OrderResult:
        if not self._connected:
            raise RuntimeError("ยังไม่ได้ connect() สำเร็จ")
        self._assert_demo()

        if self.dry_run:
            print(
                f"[DRY-RUN] จะส่ง {direction.value} {lot} lot {symbol} "
                f"sl={sl} tp={tp} (ยังไม่ได้ยิงจริง — dry_run=True)"
            )
            return OrderResult(success=True, ticket=None, message="dry_run")

        mt5 = self._mt5
        order_type = mt5.ORDER_TYPE_BUY if direction == Direction.BUY else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask if direction == Direction.BUY else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 10,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(success=False, message=f"order_send ล้มเหลว: {result}")
        return OrderResult(success=True, ticket=result.order, message="ok")

    def close_position(self, symbol: str, ticket: int, volume: float | None = None) -> OrderResult:
        """ปิด position — ถ้าไม่ระบุ volume ปิดทั้งไม้ ถ้าระบุ (< volume เดิม) = ปิดบางส่วน (partial TP)"""
        if not self._connected:
            raise RuntimeError("ยังไม่ได้ connect() สำเร็จ")
        self._assert_demo()

        if self.dry_run:
            print(f"[DRY-RUN] จะปิด position ticket={ticket} {symbol} volume={volume or 'ทั้งหมด'} "
                  f"(ยังไม่ได้ยิงจริง)")
            return OrderResult(success=True, ticket=ticket, message="dry_run")

        mt5 = self._mt5
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return OrderResult(success=False, message=f"ไม่พบ position ticket={ticket}")
        pos = positions[0]
        close_volume = round(min(volume, pos.volume), 2) if volume is not None else pos.volume
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": close_volume,
            "type": close_type,
            "position": pos.ticket,
            "price": price,
            "deviation": 10,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(success=False, message=f"order_send (close) ล้มเหลว: {result}")
        return OrderResult(success=True, ticket=result.order, message="ok")

    def modify_sl_tp(
        self, symbol: str, ticket: int, sl: float | None = None, tp: float | None = None
    ) -> OrderResult:
        """แก้ SL/TP ของ position ที่เปิดอยู่ — ใช้สำหรับ trailing stop / เลื่อน SL ไป breakeven /
        ยกเลิก TP ตอน snowball (ส่ง tp=0.0 เพื่อลบ TP ทิ้ง) ค่าที่ไม่ส่ง (None) = คงค่าเดิมไว้
        """
        if not self._connected:
            raise RuntimeError("ยังไม่ได้ connect() สำเร็จ")
        self._assert_demo()

        if self.dry_run:
            print(f"[DRY-RUN] จะแก้ SL/TP ticket={ticket} {symbol} sl={sl} tp={tp} (ยังไม่ได้ยิงจริง)")
            return OrderResult(success=True, ticket=ticket, message="dry_run")

        mt5 = self._mt5
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return OrderResult(success=False, message=f"ไม่พบ position ticket={ticket}")
        pos = positions[0]
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": pos.ticket,
            "sl": sl if sl is not None else pos.sl,
            "tp": tp if tp is not None else pos.tp,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(success=False, message=f"order_send (modify) ล้มเหลว: {result}")
        return OrderResult(success=True, ticket=ticket, message="ok")

    def disconnect(self) -> None:
        if self._connected and self._mt5 is not None:
            self._mt5.shutdown()
            self._connected = False

    def account_balance(self) -> float:
        self._assert_demo()
        return float(self._mt5.account_info().balance)

    def calc_margin(self, symbol: str, direction: Direction, lot: float, price: float) -> float | None:
        """คำนวณ margin ที่ต้องใช้เปิดไม้นี้ (หน่วยเดียวกับ currency บัญชี) — คืน None ถ้าคำนวณไม่ได้

        เรียกหลัง send_order() สำเร็จเสมอ — ไม้จริงเปิดไปแล้ว ห้ามให้ error ตรงนี้ (แค่คำนวณ
        margin เพื่อโชว์ผล) ไปขัดขวางการบันทึกไม้ลง DB (log_trade_open) ที่ตามมา จึงกันด้วย
        try/except แทนที่จะปล่อยให้ throw ขึ้นไปโดน broad except ใน live_runner.py แล้วทำให้
        open_trade_id ไม่ถูกตั้งค่า (ไม้เปิดจริงแต่ไม่มี record ใน DB เลย)
        """
        if self.dry_run or self._mt5 is None:
            return None
        try:
            mt5 = self._mt5
            order_type = mt5.ORDER_TYPE_BUY if direction == Direction.BUY else mt5.ORDER_TYPE_SELL
            margin = mt5.order_calc_margin(order_type, symbol, lot, price)
            return float(margin) if margin is not None else None
        except Exception:
            return None

    def get_position(self, ticket: int):
        """คืน position object ของ MT5 ถ้ายังเปิดอยู่ ไม่งั้นคืน None (ไม้ปิดไปแล้ว)"""
        self._assert_demo()
        positions = self._mt5.positions_get(ticket=ticket)
        return positions[0] if positions else None

    def get_closed_deal_pnl(self, ticket: int) -> float | None:
        """หลัง position ปิดแล้ว ดึงกำไร/ขาดทุนจริงจาก deal history — คืน None ถ้ายังหาไม่เจอ"""
        self._assert_demo()
        deals = self._mt5.history_deals_get(position=ticket)
        if not deals:
            return None
        return float(sum(d.profit + d.swap + d.commission for d in deals))

    def latest_closed_bars(self, symbol: str, timeframe_const: int, count: int):
        """ดึงแท่งที่ "ปิดแล้ว" เท่านั้น (ตัดแท่งกำลังก่อตัวปัจจุบันทิ้ง) — กัน lookahead ให้ live เหมือน backtest"""
        self._assert_demo()
        rates = self._mt5.copy_rates_from_pos(symbol, timeframe_const, 0, count + 1)
        if rates is None or len(rates) < 2:
            return None
        return rates[:-1]  # ตัดแท่งสุดท้าย (ยังไม่ปิด) ทิ้ง
