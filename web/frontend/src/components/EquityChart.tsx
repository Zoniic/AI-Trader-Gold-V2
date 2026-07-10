"use client";

import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import type { Trade } from "@/lib/api";

export function EquityChart({
  trades,
  initialBalance,
}: {
  trades: Trade[];
  initialBalance: number;
}) {
  // ไม้ที่ยังเปิดอยู่ (exit_time ว่าง) ไม่นับใน equity curve — รอปิดก่อนถึงจะรู้ผลจริง
  const closed = trades.filter((t) => t.exit_time != null);
  const sorted = [...closed].sort(
    (a, b) => new Date(a.exit_time!).getTime() - new Date(b.exit_time!).getTime()
  );

  let running = initialBalance;
  const data = [
    { time: "start", balance: initialBalance },
    ...sorted.map((t) => {
      running += t.pnl ?? 0;
      return {
        time: new Date(t.exit_time!).toLocaleString("th-TH", {
          dateStyle: "short",
          timeStyle: "short",
        }),
        balance: Math.round(running * 100) / 100,
      };
    }),
  ];

  if (sorted.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-border bg-surface text-sm text-muted">
        ยังไม่มีเทรดใน run นี้
      </div>
    );
  }

  return (
    <div className="h-64 rounded-xl border border-border bg-surface p-4">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis
            dataKey="time"
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            domain={["auto", "auto"]}
          />
          <Tooltip
            contentStyle={{
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--foreground)",
              fontSize: 12,
            }}
          />
          <Line
            type="monotone"
            dataKey="balance"
            stroke="var(--accent)"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
