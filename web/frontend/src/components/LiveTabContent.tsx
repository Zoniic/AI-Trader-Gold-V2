"use client";

import { useCallback, useEffect, useState } from "react";
import type { LiveStatus } from "@/lib/api";
import { LiveTeamCard } from "@/components/LiveTeamCard";
import { PortfolioEquityChart } from "@/components/PortfolioEquityChart";
import { TeamPnlBarChart } from "@/components/TeamPnlBarChart";
import { TickingNumber } from "@/components/TickingNumber";
import { LiveEquitySparkline } from "@/components/LiveEquitySparkline";
import { PnlCandleChart } from "@/components/PnlCandleChart";
import { PriceChart } from "@/components/PriceChart";

const LIVE_POLL_MS = 7000;

/**
 * เนื้อหาทั้งหมดของ Live tab — โครงสร้างใหม่: 1 ทีม = 1 การ์ดขยายได้ (accordion) ที่รวม
 * สถานะสด + metric + equity + ประวัติไม้ไว้ในที่เดียว แทนที่โครงสร้างเดิมที่แยกเป็น
 * Live Panel (สรุป) + dropdown (เลือก run) + section รายละเอียดแยกด้านล่างสุดของหน้า
 * ซึ่งต้องเลื่อน/เชื่อมโยงเอง 3 จุดสำหรับข้อมูลทีมเดียว
 */
export function LiveTabContent() {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [error, setError] = useState<string>("");

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/live/status");
      if (!res.ok) throw new Error(`โหลดสถานะ live ไม่สำเร็จ (${res.status})`);
      const data: LiveStatus = await res.json();
      setStatus(data);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "โหลดข้อมูลไม่สำเร็จ");
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, LIVE_POLL_MS);
    return () => clearInterval(interval);
  }, [load]);

  if (error) {
    return (
      <div className="rounded-xl border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
        {error}
      </div>
    );
  }

  if (!status || status.teams.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-surface px-4 py-6 text-center text-sm text-muted">
        <p className="mb-2">ยังไม่เคยรัน live_runner เลย</p>
        <p>
          สั่งรันด้วย{" "}
          <code className="text-foreground">python -m execution.live_runner</code>
        </p>
      </div>
    );
  }

  const runningCount = status.teams.filter((t) => t.is_running).length;
  const openCount = status.teams.filter((t) => t.open_position).length;
  const totalPnlToday = status.portfolio.total_pnl + status.portfolio.floating_pnl;

  return (
    <div>
      {/* ตัวเลขใหญ่ไล่นับ + กราฟรวมพอร์ต — ตอบคำถาม "ตอนนี้เงินรวมเป็นยังไง" ในแวบเดียว
          แทนที่จะต้องนั่งบวกจากการ์ดทีละใบ */}
      <div className="mb-4 rounded-xl border border-border bg-surface p-4">
        <div className="mb-1 text-xs text-muted">กำไร/ขาดทุนรวมทั้งพอร์ต (ทุกทีม รวมไม้ที่ยังเปิดอยู่)</div>
        <div
          className={`text-3xl font-semibold tabular-nums ${
            totalPnlToday >= 0 ? "text-profit" : "text-loss"
          }`}
        >
          <TickingNumber value={totalPnlToday} prefix="$" />
        </div>
        <div className="mt-1 text-xs text-muted">
          Balance รวม{" "}
          <span className="text-foreground">${status.portfolio.current_balance.toFixed(2)}</span>
          {" "}จากเงินตั้งต้น ${status.portfolio.initial_balance.toFixed(2)}
        </div>
        <div className="mt-2 border-t border-border pt-2">
          <LiveEquitySparkline points={status.portfolio.equity_curve} />
        </div>
      </div>

      {/* กราฟราคาสไตล์ TradingView + จุดเข้า/ออกไม้ของทุกทีม — ตอบ "ตอนนี้ราคาอยู่ไหน ทีมเข้าตรงไหน" */}
      <div className="mb-4">
        <PriceChart symbols={[...new Set(status.teams.map((t) => t.symbol))]} />
      </div>

      {/* สรุปต่อสินทรัพย์ — โชว์เฉพาะเมื่อพอร์ตมีมากกว่า 1 symbol (multi-asset) ไม่งั้นเป็น noise */}
      {status.portfolio.by_symbol && status.portfolio.by_symbol.length > 1 && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          {status.portfolio.by_symbol.map((s) => (
            <div key={s.symbol} className="rounded-xl border border-border bg-surface px-4 py-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-foreground">{s.symbol}</span>
                <span className="text-[10px] text-muted">{s.teams} ทีม</span>
              </div>
              <div
                className={`mt-1 text-lg font-semibold tabular-nums ${
                  s.pnl >= 0 ? "text-profit" : "text-loss"
                }`}
              >
                {s.pnl >= 0 ? "+" : ""}${s.pnl.toFixed(2)}
              </div>
              <div className="text-[10px] text-muted">
                {s.open_positions > 0 ? `${s.open_positions} ไม้เปิดอยู่` : "ไม่มีไม้เปิด"}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="mb-1 text-xs text-muted">Equity รวมทั้งพอร์ต (ไม้ที่ปิดแล้วของทุกทีม)</div>
          <PortfolioEquityChart points={status.portfolio.equity_curve} />
        </div>
        <div>
          <div className="mb-1 text-xs text-muted">กำไร/ขาดทุนแยกตามทีม</div>
          <TeamPnlBarChart data={status.portfolio.by_team} />
        </div>
      </div>

      <div className="mb-4">
        <div className="mb-1 text-xs text-muted">
          แท่งเทียน Balance รวมพอร์ต — แบ่งแท่งละ 1 ชั่วโมงตามไม้ที่ปิดจริง
        </div>
        <PnlCandleChart candles={status.portfolio.pnl_candles} />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-4 rounded-xl border border-border bg-surface px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5">
            {runningCount > 0 && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-profit opacity-75" />
            )}
            <span
              className={`relative inline-flex h-2.5 w-2.5 rounded-full ${
                runningCount > 0 ? "bg-profit" : "bg-muted"
              }`}
            />
          </span>
          <span className="text-sm font-medium text-foreground">
            {runningCount}/{status.teams.length} ทีมกำลังรันอยู่
          </span>
        </div>
        <div className="text-sm text-muted">
          {openCount > 0 ? `${openCount} ทีมมีไม้เปิดอยู่` : "ไม่มีไม้เปิดอยู่ตอนนี้"}
        </div>
      </div>

      <p className="mb-2 text-xs text-muted">
        คลิกที่การ์ดทีมไหนก็ได้เพื่อขยายดูรายละเอียด (metric, equity, ประวัติไม้) — ไม่ต้องเลื่อนหาที่อื่น
      </p>
      <div className="space-y-2">
        {status.teams.map((t) => (
          <LiveTeamCard key={t.run_id} team={t} />
        ))}
      </div>
    </div>
  );
}
