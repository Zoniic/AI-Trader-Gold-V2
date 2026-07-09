"""Dashboard อ่านผล signal/decision/trade จาก trading_log.db — อ่านอย่างเดียว ไม่แก้ข้อมูลใด ๆ

รัน: streamlit run dashboard.py

หมายเหตุเรื่อง "realtime": ตอนนี้ยังไม่มี live runner ที่เทรดต่อเนื่อง ข้อมูลจะขยับก็ต่อเมื่อมี
คนรัน run_backtest.py/run_walkforward.py ใหม่ — แดชบอร์ดนี้แค่ auto-refresh เพื่อดึงค่าล่าสุดจาก
DB มาแสดงเสมอ พอวันที่มี live runner จริง (เขียนลง DB เดียวกัน) แดชบอร์ดนี้จะเห็นข้อมูลสดทันที
โดยไม่ต้องแก้อะไรเลย
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from config import load_settings
from core.strategy import STRATEGY_REGISTRY
from persistence.db import get_decisions, get_trades, list_runs
import strategies  # noqa: F401  (import ทำให้ @register_strategy ทำงาน เติม registry)

st.set_page_config(page_title="AI Trader V2 — Dashboard", layout="wide")

settings = load_settings()

st.sidebar.title("AI Trader V2")
db_path = st.sidebar.text_input("SQLite log path", value=settings.log_db_path)
auto_refresh = st.sidebar.checkbox("รีเฟรชอัตโนมัติทุก 5 วินาที", value=True)

with st.expander(f"ℹ️ ทีมทั้งหมดในระบบทำงานยังไงบ้าง ({len(STRATEGY_REGISTRY)} ทีม)"):
    for team_name, team_cls in STRATEGY_REGISTRY.items():
        instance = team_cls()
        st.markdown(f"**`{team_name}`**")
        st.caption(team_cls.description)
        members = instance.committee_info()
        if members:
            st.caption(
                "นักเทรดในทีม: "
                + " · ".join(f"{m['name']} ({m['role']})" for m in members)
                + " — ค้านได้ไม่เกิน 1 เสียงถึงเข้าไม้"
            )
        st.code(", ".join(f"{k}={v}" for k, v in instance.params().items()), language=None)

runs_df = list_runs(db_path)

# --- ตารางแข่งขัน: ผลรันล่าสุดของแต่ละทีม เรียงตาม expectancy ---
if not runs_df.empty:
    latest_per_team = runs_df.drop_duplicates(subset=["strategy", "timeframe"], keep="first")
    standings = latest_per_team.sort_values("expectancy", ascending=False)
    st.markdown("### 🏆 ตารางแข่งขัน (ผลรันล่าสุดต่อทีมต่อ TF)")
    league_cols = ["strategy", "timeframe", "total_trades", "win_rate_pct", "profit_factor",
                   "expectancy", "final_balance", "halted_at"]
    st.dataframe(
        standings[[c for c in league_cols if c in standings.columns]].reset_index(drop=True),
        use_container_width=True,
    )

    # --- แผนที่: กราฟแบบไหนใช้ทีมไหน ---
    from backtest.regime_league import compute_regime_league

    regime_data = compute_regime_league(db_path)
    if regime_data["champions"]:
        st.markdown("### 🗺️ กราฟแบบไหน ควรใช้ทีมไหนเทรด (ขั้นต่ำ 15 ไม้/ช่อง)")
        champ_df = pd.DataFrame(regime_data["champions"])
        st.dataframe(champ_df, use_container_width=True)

    # --- จำลองพอร์ตรวมทุกทีม: เป้าผลตอบแทน/เดือน vs DD/โอกาสเจ๊ง ---
    from portfolio.simulate import simulate_portfolio

    PORTFOLIO_SELECTIONS = [
        ("trend_pullback", "M30", 1.0),
        ("london_breakout", "M30", 1.0),
        ("trend_pullback", "H1", 0.5),
        ("rsi_divergence", "M30", 0.5),
        ("donchian_breakout", "H1", 0.5),
        ("ema_cross", "M30", 0.5),
        ("vwap_reversion", "H1", 0.25),
        ("volatility_breakout", "H1", 0.25),
    ]
    with st.expander("💰 จำลองพอร์ตรวมทุกทีม — เป้าผลตอบแทน/เดือน แลกกับ DD เท่าไหร่?"):
        st.caption(
            "ทีมในพอร์ต: "
            + ", ".join(f"{s}:{tf} ({r}%)" for s, tf, r in PORTFOLIO_SELECTIONS)
        )
        rows = []
        for m in (1, 2, 4, 8):
            try:
                result = simulate_portfolio(
                    db_path, PORTFOLIO_SELECTIONS,
                    initial_balance=settings.initial_balance, risk_multiplier=float(m),
                    dd_targeting=True,
                )
            except ValueError as exc:
                st.warning(str(exc))
                break
            rets = [mo["return_pct"] for mo in result.monthly_returns]
            rows.append(
                {
                    "ตัวคูณ risk": f"{m}x",
                    "ทุนจบ": round(result.final_balance, 0),
                    "Max DD %": round(result.max_drawdown_pct, 1),
                    "เดือนเฉลี่ย %": round(sum(rets) / len(rets), 1) if rets else 0.0,
                    "เดือนแย่สุด %": round(min(rets), 1) if rets else 0.0,
                    "เดือนดีสุด %": round(max(rets), 1) if rets else 0.0,
                    "ไม้": result.taken,
                    "เจ๊ง?": "ใช่!" if result.ruined else "ไม่",
                }
            )
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        st.caption(
            "⚠ ตัวคูณสูงให้ผลตอบแทน/เดือนสูงขึ้นจริง แต่ MaxDD และโอกาสเจ๊งพุ่งไม่เป็นเส้นตรง — "
            "เป้า 100-1000%/เดือนพร้อมเงินต้นไม่หายเป็นไปไม่ได้ในทางคณิตศาสตร์ด้วย edge ปัจจุบัน"
        )

    # --- สภานักวิเคราะห์ AI ---
    from analysis.council import run_council

    council_data = run_council(db_path)
    with st.expander("🧑‍⚖️ สภานักวิเคราะห์ AI — Risk / Edge / Discipline / Psychology"):
        for key, section in council_data.items():
            st.markdown(f"**{section['focus']}**")
            if section["findings"]:
                for f in section["findings"]:
                    st.caption(f"• {f}")
            else:
                st.caption("ไม่พบประเด็นผิดปกติในรอบล่าสุด")

if runs_df.empty:
    st.warning(f"ยังไม่มีข้อมูลใน `{db_path}` — รัน `python run_backtest.py` อย่างน้อยหนึ่งครั้งก่อน")
    st.stop()

run_labels = [
    f"{row.run_id}  ({row.strategy}, เทรด {int(row.total_trades) if pd.notna(row.total_trades) else '-'})"
    for row in runs_df.itertuples()
]
selected_label = st.sidebar.selectbox("เลือก run", run_labels, index=0)
selected_run = runs_df.iloc[run_labels.index(selected_label)]["run_id"]


@st.fragment(run_every=5 if auto_refresh else None)
def render_dashboard(db_path: str, run_id: str) -> None:
    runs = list_runs(db_path)
    row = runs[runs["run_id"] == run_id]
    if row.empty:
        st.error("ไม่พบ run นี้แล้ว (อาจถูกลบไปหลังเลือก)")
        return
    run = row.iloc[0]

    st.caption(f"อัปเดตล่าสุด: {datetime.now().strftime('%H:%M:%S')}")
    st.subheader(f"กลยุทธ์: {run['strategy']}  —  run_id: `{run_id}`")

    if pd.notna(run.get("halted_at")):
        st.error(f"⚠ kill-switch ทำงานที่ {run['halted_at']} — {run['halt_reason']}")
    elif pd.isna(run.get("finished_at")):
        st.info("run นี้ยังไม่จบ (finished_at ว่าง) — อาจกำลังรันอยู่ หรือถูกขัดจังหวะ")

    cols = st.columns(6)
    cols[0].metric("เทรดทั้งหมด", int(run["total_trades"]) if pd.notna(run["total_trades"]) else "-")
    cols[1].metric("Win rate", f"{run['win_rate_pct']:.1f}%" if pd.notna(run["win_rate_pct"]) else "-")
    cols[2].metric("Profit factor", f"{run['profit_factor']:.2f}" if pd.notna(run["profit_factor"]) else "-")
    cols[3].metric(
        "Max drawdown", f"{run['max_drawdown_pct']:.1f}%" if pd.notna(run["max_drawdown_pct"]) else "-"
    )
    cols[4].metric("Expectancy", f"{run['expectancy']:.2f}" if pd.notna(run["expectancy"]) else "-")
    cols[5].metric("Balance", f"${run['final_balance']:.2f}" if pd.notna(run["final_balance"]) else "-")

    trades = get_trades(db_path, run_id)
    if not trades.empty:
        trades["exit_time"] = pd.to_datetime(trades["exit_time"])
        trades = trades.sort_values("exit_time")
        initial_balance = run["initial_balance"] if pd.notna(run["initial_balance"]) else 0.0
        trades["balance"] = trades["pnl"].cumsum() + initial_balance

        st.markdown("#### Equity Curve")
        st.line_chart(trades.set_index("exit_time")["balance"], height=300)

        st.markdown("#### รายการเทรด")
        trade_cols = [
            "entry_time", "direction", "entry", "sl", "tp", "lot",
            "exit_time", "exit_price", "pnl", "pnl_r", "mae_r", "mfe_r",
            "outcome", "regime",
        ]
        st.dataframe(
            trades[[c for c in trade_cols if c in trades.columns]],
            use_container_width=True,
            height=300,
        )

        # บทวิเคราะห์อัตโนมัติระดับ run (จาก MAE/MFE ของทุกไม้)
        from backtest.review import aggregate_review_from_rows

        review_summary = aggregate_review_from_rows(trades.to_dict(orient="records"))
        if review_summary.get("total"):
            st.markdown("#### 🔍 บทวิเคราะห์ไม้อัตโนมัติ + คำแนะนำปรับปรุง")
            st.caption(
                f"ชนะเฉลี่ย {review_summary.get('avg_win_r', 0):+.2f}R · "
                f"แพ้เฉลี่ย {review_summary.get('avg_loss_r', 0):+.2f}R · "
                f"แพ้ทั้งที่เคยกำไร≥1R: {review_summary.get('losses_were_winning_1r', 0)} ไม้ · "
                f"ชน TP แล้ววิ่งต่อ≥1R: {review_summary.get('tp_ran_on_1r', 0)}/"
                f"{review_summary.get('tp_hits_with_lookahead', 0)} ไม้"
            )
            for rec in review_summary.get("recommendations", []):
                st.info(f"💡 {rec}")

        st.markdown("#### แยกตามสภาวะตลาด (trend / range / volatile)")
        regime_group = trades.groupby(trades["regime"].fillna("unknown"))["pnl"]
        regime_summary = regime_group.agg(
            เทรด="count",
            win_rate_pct=lambda s: round((s > 0).sum() / len(s) * 100, 1),
            total_pnl=lambda s: round(s.sum(), 2),
            expectancy=lambda s: round(s.mean(), 2),
        )
        st.dataframe(regime_summary, use_container_width=True)

        # ความเห็นคณะกรรมการของเทรดล่าสุด (ถ้ามี — run เก่าก่อนระบบ committee จะไม่มี)
        with_discussion = trades[trades["discussion"].notna()].sort_values(
            "exit_time", ascending=False
        )
        if not with_discussion.empty:
            with st.expander(
                f"🗣️ ความเห็นทีมก่อนเข้าไม้ (ดู 10 ไม้ล่าสุด จากทั้งหมด {len(with_discussion)} ไม้)"
            ):
                import json as _json

                for _, tr in with_discussion.head(10).iterrows():
                    st.markdown(
                        f"**{tr['direction']} @ {tr['entry']:.2f}** "
                        f"(เข้า {tr['entry_time']} → pnl {tr['pnl']:.2f}, {tr['outcome']})"
                    )
                    try:
                        for o in _json.loads(tr["discussion"]):
                            icon = "✅" if o["approve"] else "❌"
                            st.caption(f"{icon} {o['member']} ({o['role']}): {o['comment']}")
                    except (ValueError, TypeError):
                        st.caption("(อ่านความเห็นไม่ได้)")
    else:
        st.info("ยังไม่มีเทรดใน run นี้")

    if pd.notna(run.get("config")) and run.get("config"):
        with st.expander("⚙️ Config ที่ใช้ใน run นี้ (แก้ได้ที่ configs/<team>.json)"):
            import json as _json_cfg

            try:
                st.json(_json_cfg.loads(run["config"]))
            except (ValueError, TypeError):
                st.code(str(run["config"]))

    rejected = get_decisions(db_path, run_id, approved=False)
    st.markdown(f"#### สัญญาณที่ถูกปฏิเสธ ({len(rejected)} ครั้ง)")
    if not rejected.empty:
        reason_counts = rejected["reason"].value_counts().reset_index()
        reason_counts.columns = ["เหตุผล", "จำนวนครั้ง"]
        st.dataframe(reason_counts, use_container_width=True)
    else:
        st.caption("ไม่มีสัญญาณที่ถูกปฏิเสธใน run นี้")


render_dashboard(db_path, selected_run)
