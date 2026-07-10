"use client";

import { useCallback, useEffect, useState } from "react";
import type { LiveStatus } from "@/lib/api";
import { LiveTeamCard } from "@/components/LiveTeamCard";

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
  const totalPnlToday = status.teams.reduce((sum, t) => sum + t.total_pnl + t.floating_pnl, 0);

  return (
    <div>
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
        <div className="ml-auto text-sm">
          <span className="text-muted">กำไร/ขาดทุนรวมวันนี้ (รวมไม้ที่ยังเปิดอยู่): </span>
          <span className={totalPnlToday >= 0 ? "text-profit" : "text-loss"}>
            {totalPnlToday >= 0 ? "+" : ""}
            {totalPnlToday.toFixed(2)}
          </span>
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
