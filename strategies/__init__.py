"""import ที่นี่เพื่อให้ decorator @register_strategy ทำงานและลงทะเบียนใน STRATEGY_REGISTRY

เพิ่มกลยุทธ์ใหม่: สร้างไฟล์ในโฟลเดอร์นี้ inherit Strategy + แปะ @register_strategy
แล้วเพิ่มบรรทัด import ไว้ด้านล่างนี้
"""
from . import ema_cross  # noqa: F401  ทีม 1 Golden Cross (trend-following)
from . import mean_reversion  # noqa: F401  ทีม 2 Rubber Band (BB+RSI reversion)
from . import donchian_breakout  # noqa: F401  ทีม 3 Turtle Squad (channel breakout)
from . import london_breakout  # noqa: F401  ทีม 4 Session Raiders (session breakout)
from . import macd_momentum  # noqa: F401  ทีม 5 Momentum Five (MACD)
from . import rsi_divergence  # noqa: F401  ทีม 6 Divergence Hunters (reversal)
from . import vwap_reversion  # noqa: F401  ทีม 7 VWAP Desk (institutional fade)
from . import trend_pullback  # noqa: F401  ทีม 8 Dip Buyers (pullback continuation)
from . import volatility_breakout  # noqa: F401  ทีม 9 Range Expanders (Larry Williams)
from . import sr_bounce  # noqa: F401  ทีม 10 Level Keepers (price action S/R)
from . import fibonacci_confluence  # noqa: F401  ทีม 11 Fib Confluence Desk (Fibonacci confluence)
# ทีม 12 momentum_scalper และทีม 13 rule_breaker ถูกถอดจาก registry (2026-07-14) —
# ทั้งคู่พิสูจน์แล้วว่าไม่มี edge (PF < 1 ทุก config, kill-switch ทุกรอบ ดูประวัติใน configs/*.json)
# โค้ดยังอยู่ในโฟลเดอร์นี้เป็นบันทึกการวิจัย ถ้าจะชุบชีวิตให้ redesign สัญญาณ + validate ผ่านก่อนค่อย import กลับ
from . import quick_cash  # noqa: F401  ทีม 14 เก็บเงินด่วน (สายซิ่งมีวินัย burst momentum)
from . import smc_flow  # noqa: F401  ทีม 15 นายธนาคารเงา (Smart Money Concepts เต็มลำดับ)
