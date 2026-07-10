"use client";

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

/** เทียบกำไร/ขาดทุน (realized + floating) ของแต่ละทีมแบบ bar chart แนวนอน — เห็นทันทีว่า
 * ทีมไหนแบกพอร์ต ทีมไหนดึงพอร์ตลง แทนที่จะต้องไล่อ่านตัวเลขจากการ์ดทีละใบ
 */
export function TeamPnlBarChart({
  data,
}: {
  data: { strategy: string; timeframe: string | null; pnl: number }[];
}) {
  if (data.length === 0) return null;

  const sorted = [...data].sort((a, b) => b.pnl - a.pnl);
  const chartData = sorted.map((d) => ({
    name: `${d.strategy}:${d.timeframe ?? "-"}`,
    pnl: d.pnl,
  }));
  const height = Math.max(160, chartData.length * 32);

  return (
    <div className="rounded-xl border border-border bg-surface p-4" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 20, left: 10, bottom: 0 }}>
          <XAxis type="number" tick={{ fill: "var(--muted)", fontSize: 11 }} />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            width={130}
          />
          <Tooltip
            contentStyle={{
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--foreground)",
              fontSize: 12,
            }}
            formatter={(value) => [`${Number(value) >= 0 ? "+" : ""}$${Number(value).toFixed(2)}`, "PnL"]}
          />
          <Bar dataKey="pnl" radius={[0, 4, 4, 0]}>
            {chartData.map((d) => (
              <Cell key={d.name} fill={d.pnl >= 0 ? "var(--profit)" : "var(--loss)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
