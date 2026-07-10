"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";

/** กราฟ equity รวมทั้งพอร์ต (ทุกทีมบวกกัน) — ตัวใหญ่ วางบนสุดของ Live tab ให้เห็นภาพรวม
 * เงินทั้งก้อนแบบวันเดียวจบ ไม่ต้องนั่งบวกจากการ์ดทีละใบ
 */
export function PortfolioEquityChart({
  points,
}: {
  points: { time: string; balance: number }[];
}) {
  if (points.length < 2) {
    return (
      <div className="flex h-56 items-center justify-center rounded-xl border border-border bg-surface text-sm text-muted">
        ยังไม่มีไม้ปิดพอจะวาดกราฟรวมพอร์ต (ต้องมีอย่างน้อย 1 ไม้ปิดจากทีมใดก็ได้)
      </div>
    );
  }

  const data = points.map((p, i) => ({
    ...p,
    label:
      p.time === "start"
        ? "เริ่มต้น"
        : new Date(p.time).toLocaleString("th-TH", { dateStyle: "short", timeStyle: "short" }),
    idx: i,
  }));
  const first = data[0].balance;
  const last = data[data.length - 1].balance;
  const up = last >= first;

  return (
    <div className="h-56 rounded-xl border border-border bg-surface p-4">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="portfolioFill" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="5%"
                stopColor={up ? "var(--profit)" : "var(--loss)"}
                stopOpacity={0.35}
              />
              <stop offset="95%" stopColor={up ? "var(--profit)" : "var(--loss)"} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis tick={{ fill: "var(--muted)", fontSize: 11 }} domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--foreground)",
              fontSize: 12,
            }}
            formatter={(value) => [`$${Number(value).toFixed(2)}`, "Balance รวม"]}
          />
          <Area
            type="monotone"
            dataKey="balance"
            stroke={up ? "var(--profit)" : "var(--loss)"}
            strokeWidth={2.5}
            fill="url(#portfolioFill)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
