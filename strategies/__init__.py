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
