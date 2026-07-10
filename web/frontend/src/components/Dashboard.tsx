"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { logout } from "@/app/actions/auth";
import { MetricCard } from "@/components/MetricCard";
import { EquityChart } from "@/components/EquityChart";
import { TradeTable } from "@/components/TradeTable";
import { RegimeBreakdown } from "@/components/RegimeBreakdown";
import { ReviewSummaryCard } from "@/components/ReviewSummaryCard";
import { TeamsInfo } from "@/components/TeamsInfo";
import { LeagueTable } from "@/components/LeagueTable";
import { RegimeChampions } from "@/components/RegimeChampions";
import { PortfolioSimulator } from "@/components/PortfolioSimulator";
import { CouncilReport } from "@/components/CouncilReport";
import { LivePanel } from "@/components/LivePanel";
import type { RunDetail, RunSummary } from "@/lib/api";

const REFRESH_MS = 5000;
const isLiveRun = (runId: string) => runId.startsWith("live_");

type Tab = "backtest" | "live";

function fmtPct(n: number | null): string {
  return n === null ? "-" : `${n.toFixed(1)}%`;
}
function fmtNum(n: number | null, digits = 2): string {
  return n === null ? "-" : n.toFixed(digits);
}
function fmtMoney(n: number | null): string {
  return n === null ? "-" : `$${n.toFixed(2)}`;
}

export function Dashboard() {
  const [tab, setTab] = useState<Tab>("backtest");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const [error, setError] = useState<string>("");
  const selectedRunIdRef = useRef(selectedRunId);
  selectedRunIdRef.current = selectedRunId;
  const detailSectionRef = useRef<HTMLDivElement>(null);

  const jumpToRunDetail = useCallback((runId: string) => {
    setSelectedRunId(runId);
    // เลื่อนหลัง tick ถัดไปให้ DOM render เสร็จก่อน (กันกรณี section ยังไม่เคย mount)
    requestAnimationFrame(() => {
      detailSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, []);

  const backtestRuns = useMemo(() => runs.filter((r) => !isLiveRun(r.run_id)), [runs]);
  const liveRuns = useMemo(() => runs.filter((r) => isLiveRun(r.run_id)), [runs]);

  const loadRuns = useCallback(async () => {
    try {
      const res = await fetch("/api/runs");
      if (!res.ok) throw new Error(`โหลดรายการ run ไม่สำเร็จ (${res.status})`);
      const data: RunSummary[] = await res.json();
      setRuns(data);
      setError("");
      if (!selectedRunIdRef.current) {
        const firstBacktest = data.find((r) => !isLiveRun(r.run_id));
        if (firstBacktest) setSelectedRunId(firstBacktest.run_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "โหลดข้อมูลไม่สำเร็จ");
    }
  }, []);

  const loadDetail = useCallback(async (runId: string) => {
    if (!runId) return;
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
      if (!res.ok) throw new Error(`โหลดข้อมูล run ไม่สำเร็จ (${res.status})`);
      const data: RunDetail = await res.json();
      setDetail(data);
      setLastUpdated(new Date().toLocaleTimeString("th-TH"));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "โหลดข้อมูลไม่สำเร็จ");
    }
  }, []);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (selectedRunId) loadDetail(selectedRunId);
  }, [selectedRunId, loadDetail]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      loadRuns();
      if (selectedRunIdRef.current) loadDetail(selectedRunIdRef.current);
    }, REFRESH_MS);
    return () => clearInterval(interval);
  }, [autoRefresh, loadRuns, loadDetail]);

  // สลับแท็บแล้วเลือก run เริ่มต้นของแท็บนั้นให้อัตโนมัติ ถ้า run ที่เลือกอยู่ไม่ตรงประเภท
  const switchTab = (next: Tab) => {
    setTab(next);
    const stillValid =
      next === "backtest" ? !isLiveRun(selectedRunId) : isLiveRun(selectedRunId);
    if (!stillValid) {
      const pool = next === "backtest" ? backtestRuns : liveRuns;
      setSelectedRunId(pool[0]?.run_id ?? "");
      setDetail(null);
    }
  };

  const visibleRuns = tab === "backtest" ? backtestRuns : liveRuns;
  const detailMatchesTab = detail
    ? isLiveRun(detail.run.run_id) === (tab === "live")
    : false;

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">
            🥇 AI Trader V2 — Dashboard
          </h1>
          <p className="text-xs text-muted">
            {lastUpdated ? `อัปเดตล่าสุด: ${lastUpdated}` : "กำลังโหลด..."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            รีเฟรชอัตโนมัติ
          </label>
          <form action={logout}>
            <button
              type="submit"
              className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted hover:text-foreground"
            >
              ออกจากระบบ
            </button>
          </form>
        </div>
      </header>

      {/* แท็บหลัก: แยกให้ชัดว่ากำลังดูข้อมูลจำลองย้อนหลัง (backtest) หรือของจริงที่กำลังรัน (live) */}
      <div className="mb-6 flex gap-2 rounded-xl border border-border bg-surface p-1.5">
        <button
          onClick={() => switchTab("backtest")}
          className={`flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors ${
            tab === "backtest"
              ? "bg-accent text-background"
              : "text-muted hover:text-foreground"
          }`}
        >
          📊 Backtest — จำลองย้อนหลัง
          <span className="ml-2 text-xs opacity-70">({backtestRuns.length} runs)</span>
        </button>
        <button
          onClick={() => switchTab("live")}
          className={`flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors ${
            tab === "live"
              ? "bg-profit text-background"
              : "text-muted hover:text-foreground"
          }`}
        >
          🟢 Live Test — เทรดจริง/กระดาษตอนนี้
          <span className="ml-2 text-xs opacity-70">({liveRuns.length} runs)</span>
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-loss/40 bg-loss/10 px-4 py-2 text-sm text-loss">
          {error}
        </div>
      )}

      {tab === "live" && (
        <>
          <LivePanel onSelectRun={jumpToRunDetail} />

          {liveRuns.length > 0 && (
            <div className="mb-3">
              <label htmlFor="live-run-select" className="mb-1 block text-sm font-medium text-muted">
                ดูประวัติย้อนหลังของ run ไหน?
              </label>
              <p className="mb-2 text-xs text-muted">
                เลือกแล้วกราฟ + ตารางเทรดด้านล่างสุดของหน้าจะเปลี่ยนไปตาม run ที่เลือก
                (ไม่กระทบสถานะ live ด้านบนนี้ ซึ่งอัปเดตสดตลอด)
              </p>
              <select
                id="live-run-select"
                value={isLiveRun(selectedRunId) ? selectedRunId : ""}
                onChange={(e) => setSelectedRunId(e.target.value)}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground sm:w-auto"
              >
                <option value="" disabled>
                  เลือก live run
                </option>
                {liveRuns.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.strategy}:{r.timeframe} — เริ่ม {r.started_at}
                  </option>
                ))}
              </select>
            </div>
          )}

          {liveRuns.length === 0 && (
            <p className="mb-6 rounded-xl border border-border bg-surface p-4 text-sm text-muted">
              ยังไม่เคยรัน live_runner เลย — สั่งรันด้วย{" "}
              <code className="text-foreground">python -m execution.live_runner</code>
            </p>
          )}
        </>
      )}

      {tab === "backtest" && (
        <>
          <div className="mb-3">
            <label htmlFor="backtest-run-select" className="mb-1 block text-sm font-medium text-muted">
              ดูรายละเอียด run ไหน?
            </label>
            <p className="mb-2 text-xs text-muted">
              เลือกแล้วกราฟ + ตารางเทรดด้านล่างสุดของหน้าจะเปลี่ยนไปตาม run ที่เลือก
              (การ์ดตารางแข่งขัน/พอร์ตจำลอง/สภาวิเคราะห์ด้านล่างเป็นอิสระ ไม่ผูกกับตัวเลือกนี้)
            </p>
            <select
              id="backtest-run-select"
              value={!isLiveRun(selectedRunId) ? selectedRunId : ""}
              onChange={(e) => setSelectedRunId(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground sm:w-auto"
            >
              {backtestRuns.map((r) => (
                <option key={r.run_id} value={r.run_id} title={r.run_id}>
                  {r.strategy}:{r.timeframe ?? "H1"} — {r.total_trades ?? "-"} ไม้ —{" "}
                  {r.started_at.slice(0, 16).replace("T", " ")}
                </option>
              ))}
            </select>
          </div>

          <h2 className="mb-1 mt-8 text-xs font-semibold uppercase tracking-wide text-muted">
            การ์ดด้านล่างนี้ไม่ขึ้นกับตัวเลือกด้านบน — สรุปภาพรวมทุกทีมเสมอ
          </h2>

          <LeagueTable runs={backtestRuns} onSelectRun={jumpToRunDetail} />

          <RegimeChampions />

          <PortfolioSimulator />

          <CouncilReport />

          <TeamsInfo />

          <h2 className="mb-1 mt-8 text-xs font-semibold uppercase tracking-wide text-muted">
            ↓ รายละเอียดของ run ที่เลือกไว้ด้านบน ↓
          </h2>
        </>
      )}

      <div ref={detailSectionRef} className="scroll-mt-4">
      {!detail && !error && (
        <p className="text-sm text-muted">กำลังโหลดข้อมูล...</p>
      )}

      {detail && detailMatchesTab && (
        <>
          <div className="mb-2 flex items-center gap-2 text-sm text-muted">
            <span
              className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                isLiveRun(detail.run.run_id)
                  ? "bg-profit/20 text-profit"
                  : "bg-accent/20 text-accent"
              }`}
            >
              {isLiveRun(detail.run.run_id) ? "LIVE" : "BACKTEST"}
            </span>
            กลยุทธ์: <span className="text-foreground">{detail.run.strategy}</span>{" "}
            — run_id: <code className="text-foreground" title={detail.run.run_id}>
              {detail.run.run_id}
            </code>
          </div>

          {detail.run.halted_at && (
            <div className="mb-4 rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-sm text-accent">
              ⚠ kill-switch ทำงานที่ {detail.run.halted_at} — {detail.run.halt_reason}
            </div>
          )}

          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <MetricCard label="เทรดทั้งหมด" value={String(detail.run.total_trades ?? "-")} />
            <MetricCard
              label="Win rate"
              value={fmtPct(detail.run.win_rate_pct)}
              tone={
                (detail.run.win_rate_pct ?? 0) >= 50 ? "profit" : "loss"
              }
            />
            <MetricCard
              label="Profit factor"
              value={fmtNum(detail.run.profit_factor, 3)}
              tone={(detail.run.profit_factor ?? 0) >= 1 ? "profit" : "loss"}
            />
            <MetricCard
              label="Max drawdown"
              value={fmtPct(detail.run.max_drawdown_pct)}
              tone="loss"
            />
            <MetricCard
              label="Expectancy"
              value={fmtNum(detail.run.expectancy)}
              tone={(detail.run.expectancy ?? 0) >= 0 ? "profit" : "loss"}
            />
            <MetricCard
              label="Balance"
              value={fmtMoney(detail.run.final_balance)}
            />
          </div>

          <h2 className="mb-2 text-sm font-medium text-muted">Equity Curve</h2>
          <div className="mb-6">
            <EquityChart
              trades={detail.trades}
              initialBalance={detail.run.initial_balance ?? 0}
            />
          </div>

          <h2 className="mb-2 text-sm font-medium text-muted">แยกตามสภาวะตลาด</h2>
          <div className="mb-6">
            <RegimeBreakdown data={detail.regime_breakdown} />
          </div>

          <h2 className="mb-2 text-sm font-medium text-muted">
            🔍 บทวิเคราะห์ไม้อัตโนมัติ (MAE/MFE) + คำแนะนำปรับปรุง
          </h2>
          <div className="mb-6">
            <ReviewSummaryCard summary={detail.review_summary} />
          </div>

          <h2 className="mb-2 text-sm font-medium text-muted">รายการเทรด</h2>
          <div className="mb-6">
            <TradeTable trades={detail.trades} />
          </div>

          {detail.config && (
            <details className="mb-6 rounded-xl border border-border bg-surface">
              <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-foreground">
                ⚙️ Config ที่ใช้ใน run นี้ (สำหรับตามรอย/ปรับจูน — แก้ได้ที่ configs/
                {detail.run.strategy}.json)
              </summary>
              <pre className="overflow-auto px-4 pb-4 text-xs text-muted">
                {JSON.stringify(detail.config, null, 2)}
              </pre>
            </details>
          )}

          <h2 className="mb-2 text-sm font-medium text-muted">
            สัญญาณที่ถูกปฏิเสธ ({detail.rejected_count} ครั้ง)
          </h2>
          {detail.rejected_reasons.length > 0 ? (
            <ul className="rounded-xl border border-border bg-surface p-4 text-sm">
              {detail.rejected_reasons.map((r) => (
                <li
                  key={r.reason}
                  className="flex justify-between border-b border-border py-1.5 last:border-0"
                >
                  <span className="text-muted">{r.reason}</span>
                  <span className="text-foreground">{r.count}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted">
              ไม่มีสัญญาณที่ถูกปฏิเสธใน run นี้
            </p>
          )}
        </>
      )}
      </div>
    </div>
  );
}
