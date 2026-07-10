"use client";

import { useCallback, useEffect, useState } from "react";
import type { LiveStatus } from "@/lib/api";

const LIVE_POLL_MS = 7000; // poll ทุก 5-10 วิ ตามที่ตกลง

function fmtMoney(n: number): string {
  return `$${n.toFixed(2)}`;
}

export function LivePanel({ onSelectRun }: { onSelectRun?: (runId: string) => void }) {
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
      <div className="mb-6 rounded-xl border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
        {error}
      </div>
    );
  }

  if (!status || !status.active) {
    return (
      <div className="mb-6 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted">
        🔴 ไม่มี live/paper runner ทำงานอยู่ตอนนี้ — สั่งรันด้วย{" "}
        <code className="text-foreground">python -m execution.live_runner</code>
      </div>
    );
  }

  return (
    <div className="mb-6 rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-profit opacity-75" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-profit" />
        </span>
        <h2 className="text-sm font-medium text-foreground">
          🟢 Live Paper Trading — อัปเดตทุก {LIVE_POLL_MS / 1000} วินาที
        </h2>
      </div>
      <p className="mb-2 text-xs text-muted">
        คลิกการ์ดทีมไหนก็ได้เพื่อดูประวัติไม้ทั้งหมด (รวมที่ปิดไปแล้ว) ของทีมนั้นด้านล่างสุดของหน้า
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {status.teams.map((t) => (
          <button
            key={t.run_id}
            type="button"
            onClick={() => onSelectRun?.(t.run_id)}
            className="rounded-lg border border-border bg-background px-3 py-2.5 text-left transition-colors hover:border-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="text-sm font-medium text-foreground">
                {t.strategy}:{t.timeframe}
              </span>
              <span
                className={`h-2 w-2 rounded-full ${
                  t.is_running ? "bg-profit" : "bg-muted"
                }`}
                title={t.is_running ? "กำลังรัน" : "หยุดแล้ว"}
              />
            </div>
            {t.open_position ? (
              <div className="mb-1 space-y-0.5 rounded-md bg-accent/10 px-2 py-1.5 text-xs text-accent">
                <div className="font-medium">
                  🔵 {t.open_position.direction} {t.open_position.lot} lot @ {t.open_position.entry}
                  {t.open_position.ticket ? ` (ticket ${t.open_position.ticket})` : " (dry-run)"}
                </div>
                <div className="text-[11px] text-muted">
                  เปิดเมื่อ {t.open_position.entry_time}
                </div>
                <div className="text-[11px] text-muted">
                  SL {t.open_position.sl} · TP {t.open_position.tp}
                </div>
                {t.open_position.current_price != null && (
                  <div className="text-[11px] text-muted">
                    ราคาปัจจุบัน {t.open_position.current_price}
                    {t.open_position.floating_pnl != null && (
                      <span className={t.open_position.floating_pnl >= 0 ? " text-profit" : " text-loss"}>
                        {" "}({t.open_position.floating_pnl >= 0 ? "+" : ""}
                        {t.open_position.floating_pnl.toFixed(2)})
                      </span>
                    )}
                  </div>
                )}
                {t.open_position.margin_used != null && (
                  <div className="text-[11px] text-muted">
                    Margin {fmtMoney(t.open_position.margin_used)}
                    {t.open_position.margin_pct != null && ` (${t.open_position.margin_pct}%)`}
                  </div>
                )}
                {t.open_position.reason && (
                  <div className="truncate text-[11px] text-muted" title={t.open_position.reason}>
                    เหตุผล: {t.open_position.reason}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-xs text-muted">ไม่มีไม้เปิดอยู่</div>
            )}
            <div className="mt-1 flex justify-between text-xs">
              <span className="text-muted">วันนี้ {t.closed_trades_today} ไม้</span>
              <span className={t.total_pnl >= 0 ? "text-profit" : "text-loss"}>
                {fmtMoney(t.total_pnl)}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
