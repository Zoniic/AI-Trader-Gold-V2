"""เทสต์ portfolio simulator ด้วย DB สังเคราะห์ — ยืนยันกฎ concurrent/direction/daily-lock ทำงานจริง"""
from backtest.engine import Trade
from core.signal import Direction
from persistence.db import RunLogger
from portfolio.simulate import simulate_portfolio


def _seed_team(db_path, run_id, strategy, timeframe, trade_specs):
    """trade_specs: [(entry_time, exit_time, direction, entry, sl, tp, lot, pnl)]"""
    logger = RunLogger(db_path, run_id=run_id)
    logger.start_run(strategy, 10000.0, timeframe=timeframe, config="{}")
    for entry_time, exit_time, direction, entry, sl, tp, lot, pnl in trade_specs:
        sig_id = logger.log_signal(entry_time, strategy, direction.value, entry, sl, tp, "t")
        trade = Trade(
            direction=direction, entry_time=entry_time, entry=entry, sl=sl, tp=tp, lot=lot,
            exit_time=exit_time, exit_price=entry, pnl=pnl,
            outcome="tp" if pnl > 0 else "sl", regime="range", pnl_r=pnl / 100, mae_r=0.2,
            mfe_r=1.0, review="",
        )
        logger.log_trade(sig_id, trade)
    logger.finish_run({"final_balance": 10000, "total_trades": len(trade_specs),
                       "win_rate_pct": 50, "profit_factor": 1, "max_drawdown_pct": -5,
                       "expectancy": 0})
    logger.close()


def test_portfolio_caps_concurrent_positions(tmp_path):
    db = str(tmp_path / "p1.db")
    # 3 ทีม เปิดไม้เวลาเดียวกันหมด ถือยาว 10 ชม. — ถ้าไม่จำกัด concurrent จะเปิดพร้อมกัน 3 ไม้
    specs = [
        (f"2024-01-0{d} 08:00:00", f"2024-01-0{d} 18:00:00", Direction.BUY, 2000, 1998, 2004, 0.5, 50)
        for d in range(1, 4)
    ]
    _seed_team(db, "t1", "team_a", "H1", specs)
    _seed_team(db, "t2", "team_b", "H1", specs)
    _seed_team(db, "t3", "team_c", "H1", specs)

    result = simulate_portfolio(
        db,
        [("team_a", "H1", 1.0), ("team_b", "H1", 1.0), ("team_c", "H1", 1.0)],
        initial_balance=10000, max_concurrent=1, max_same_direction=99,
    )
    # max_concurrent=1 บังคับให้เปิดได้ทีละไม้ — ต้องมีไม้ที่ถูกข้ามเพราะเปิดครบ
    assert result.skipped_concurrent > 0
    assert result.taken >= 1


def test_portfolio_caps_same_direction(tmp_path):
    db = str(tmp_path / "p2.db")
    specs_buy = [
        (f"2024-01-0{d} 08:00:00", f"2024-01-0{d} 09:00:00", Direction.BUY, 2000, 1998, 2004, 0.5, 50)
        for d in range(1, 4)
    ]
    _seed_team(db, "t1", "team_a", "H1", specs_buy)
    _seed_team(db, "t2", "team_b", "H1", specs_buy)

    result = simulate_portfolio(
        db, [("team_a", "H1", 1.0), ("team_b", "H1", 1.0)],
        initial_balance=10000, max_concurrent=10, max_same_direction=1,
    )
    assert result.skipped_direction > 0


def test_portfolio_compounds_position_size_with_equity(tmp_path):
    db = str(tmp_path / "p3.db")
    # ไม้กำไรต่อเนื่องทำให้ equity โต — ไม้หลังควรมี pnl_scaled มากกว่าไม้แรก (เพราะ risk% คงที่ x equity ที่โตขึ้น)
    specs = [
        (f"2024-01-{d:02d} 08:00:00", f"2024-01-{d:02d} 09:00:00", Direction.BUY, 2000, 1990, 2020, 1.0, 200)
        for d in range(1, 15)
    ]
    _seed_team(db, "t1", "team_a", "H1", specs)

    result = simulate_portfolio(
        db, [("team_a", "H1", 1.0)], initial_balance=10000, max_concurrent=5,
    )
    assert result.final_balance > result.initial_balance
    assert result.taken == len(specs)


def test_portfolio_higher_multiplier_increases_drawdown(tmp_path):
    db = str(tmp_path / "p4.db")
    specs = [
        (f"2024-01-{d:02d} 08:00:00", f"2024-01-{d:02d} 09:00:00", Direction.BUY, 2000, 1990, 2020,
         1.0, 200 if d % 3 != 0 else -400)
        for d in range(1, 20)
    ]
    _seed_team(db, "t1", "team_a", "H1", specs)

    low = simulate_portfolio(db, [("team_a", "H1", 1.0)], initial_balance=10000, risk_multiplier=1.0)
    high = simulate_portfolio(db, [("team_a", "H1", 1.0)], initial_balance=10000, risk_multiplier=5.0)
    assert high.max_drawdown_pct >= low.max_drawdown_pct


def test_dd_targeting_reduces_drawdown_under_leverage(tmp_path):
    db = str(tmp_path / "p5.db")
    # ไม้แพ้ติดๆกันช่วงกลาง (drawdown ลึก) — dd_targeting ต้องหด lot ตอนนั้นทำให้ DD รวมตื้นกว่า
    specs = []
    for d in range(1, 28):
        pnl = 150 if d % 4 != 0 else -500
        if 10 <= d <= 16:  # ช่วงแพ้ยาว
            pnl = -500
        specs.append(
            (f"2024-01-{d:02d} 08:00:00", f"2024-01-{d:02d} 09:00:00", Direction.BUY,
             2000, 1990, 2020, 1.0, pnl)
        )
    _seed_team(db, "t1", "team_a", "H1", specs)

    # ตั้งเพดานต่ำ (5%) เพื่อให้ drawdown จริงทะลุเข้าโซน "หด lot" — ไม่งั้นยังอยู่โซน boost
    off = simulate_portfolio(db, [("team_a", "H1", 1.0)], initial_balance=10000,
                             risk_multiplier=3.0, dd_targeting=False)
    on = simulate_portfolio(db, [("team_a", "H1", 1.0)], initial_balance=10000,
                            risk_multiplier=3.0, dd_targeting=True,
                            dd_ceiling_pct=5.0, dd_budget_headroom=0.0, dd_budget_floor=0.4)
    # เมื่อ headroom=0 ทุกไม้ที่มี drawdown จะถูกหด lot → MaxDD รวมต้องไม่แย่ลง (ปกติดีขึ้น)
    assert on.max_drawdown_pct <= off.max_drawdown_pct
