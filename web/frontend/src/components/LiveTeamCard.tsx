"use client";

import { useState } from "react";
import type { LiveTeamStatus } from "@/lib/api";
import { LiveEquitySparkline } from "@/components/LiveEquitySparkline";
import { TradeTable } from "@/components/TradeTable";

function fmtMoney(n: number): string {
  return `${n >= 0 ? "+" : ""}$${n.toFixed(2)}`;
}
function fmtPct(n: number | null): string {
  return n === null ? "-" : `${n.toFixed(1)}%`;
}
function fmtNum(n: number | null, digits = 2): string {
  return n === null ? "-" : n.toFixed(digits);
}

/**
 * การ์ดเดียวต่อทีม รวมทุกอย่าง (สถานะสด + metric + equity + ประวัติไม้) ไว้ในที่เดียว —
 * แทนที่โครงสร้างเดิมที่ต้องดู Live Panel (สรุป) + dropdown (เลือก run) + section แยกด้านล่าง
 * (3 จุด กระจายกัน) คลิกหัวการ์ดเพื่อขยาย/ย่อ ไม่ต้องเลื่อนหาที่อื่น
 */
export function LiveTeamCard({ team }: { team: LiveTeamStatus }) {
  const [expanded, setExpanded] = useState(false);
  const pnlToday = team.total_pnl + team.floating_pnl;

  return (
    <div className="rounded-xl border border-border bg-surface">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        aria-expanded={expanded}
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className={`h-2.5 w-2.5 shrink-0 rounded-full ${
              team.is_running ? "bg-profit" : "bg-muted"
            }`}
            title={team.is_running ? "กำลังรัน" : "หยุดแล้ว"}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">
                {team.strategy}:{team.timeframe}
              </span>
              {team.open_position && (
                <span className="rounded bg-accent/20 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                  เปิดไม้อยู่
                </span>
              )}
            </div>
            <div className="text-xs text-muted">
              {team.total_trades} ไม้ · Win {fmtPct(team.win_rate_pct)} · Balance $
              {team.current_balance.toFixed(2)}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className={`text-sm font-medium ${pnlToday >= 0 ? "text-profit" : "text-loss"}`}>
            {fmtMoney(pnlToday)}
          </span>
          <span className={`text-muted transition-transform ${expanded ? "rotate-180" : ""}`}>▾</span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-border px-4 py-3">
          {team.open_position ? (
            <div className="mb-3 space-y-0.5 rounded-md bg-accent/10 px-3 py-2 text-xs text-accent">
              <div className="font-medium">
                🔵 {team.open_position.direction} {team.open_position.lot} lot @{" "}
                {team.open_position.entry}
                {team.open_position.ticket
                  ? ` (ticket ${team.open_position.ticket})`
                  : " (dry-run)"}
              </div>
              <div className="text-[11px] text-muted">เปิดเมื่อ {team.open_position.entry_time}</div>
              <div className="text-[11px] text-muted">
                SL {team.open_position.sl} · TP {team.open_position.tp}
              </div>
              {team.open_position.current_price != null && (
                <div className="text-[11px] text-muted">
                  ราคาปัจจุบัน {team.open_position.current_price}
                  {team.open_position.floating_pnl != null && (
                    <span
                      className={
                        team.open_position.floating_pnl >= 0 ? " text-profit" : " text-loss"
                      }
                    >
                      {" "}
                      ({team.open_position.floating_pnl >= 0 ? "+" : ""}
                      {team.open_position.floating_pnl.toFixed(2)})
                    </span>
                  )}
                </div>
              )}
              {team.open_position.margin_used != null && (
                <div className="text-[11px] text-muted">
                  Margin ${team.open_position.margin_used.toFixed(2)}
                  {team.open_position.margin_pct != null && ` (${team.open_position.margin_pct}%)`}
                </div>
              )}
              {team.open_position.reason && (
                <div className="truncate text-[11px] text-muted" title={team.open_position.reason}>
                  เหตุผล: {team.open_position.reason}
                </div>
              )}
            </div>
          ) : (
            <div className="mb-3 text-xs text-muted">ไม่มีไม้เปิดอยู่ตอนนี้</div>
          )}

          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-lg border border-border bg-background px-2.5 py-2">
              <div className="text-[10px] text-muted">Win rate</div>
              <div className="text-sm font-medium text-foreground">{fmtPct(team.win_rate_pct)}</div>
            </div>
            <div className="rounded-lg border border-border bg-background px-2.5 py-2">
              <div className="text-[10px] text-muted">Profit factor</div>
              <div className="text-sm font-medium text-foreground">{fmtNum(team.profit_factor, 3)}</div>
            </div>
            <div className="rounded-lg border border-border bg-background px-2.5 py-2">
              <div className="text-[10px] text-muted">Expectancy</div>
              <div className="text-sm font-medium text-foreground">{fmtNum(team.expectancy)}</div>
            </div>
            <div className="rounded-lg border border-border bg-background px-2.5 py-2">
              <div className="text-[10px] text-muted">กำไรสะสม (ไม้ปิด)</div>
              <div
                className={`text-sm font-medium ${team.total_pnl >= 0 ? "text-profit" : "text-loss"}`}
              >
                {fmtMoney(team.total_pnl)}
              </div>
            </div>
          </div>

          <div className="mb-1 text-xs text-muted">Equity (ไม้ที่ปิดแล้ว)</div>
          <div className="mb-3 rounded-lg border border-border bg-background">
            <LiveEquitySparkline points={team.equity_curve} />
          </div>

          <div className="mb-1 text-xs text-muted">ประวัติไม้ล่าสุด</div>
          <TradeTable trades={team.recent_trades} />
        </div>
      )}
    </div>
  );
}
