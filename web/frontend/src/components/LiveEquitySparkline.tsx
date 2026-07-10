"use client";

import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";

/** เส้น equity แบบย่อ (sparkline) ในการ์ดทีม — ไม่มีแกน X เพื่อประหยัดพื้นที่ ใช้ tooltip ดูค่าตอน hover แทน */
export function LiveEquitySparkline({
  points,
}: {
  points: { time: string; balance: number }[];
}) {
  if (points.length < 2) {
    return (
      <div className="flex h-16 items-center justify-center text-xs text-muted">
        ยังไม่มีไม้ปิดพอจะวาดกราฟ (ต้องมีอย่างน้อย 2 ไม้)
      </div>
    );
  }

  return (
    <div className="h-16 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
          <YAxis hide domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--foreground)",
              fontSize: 11,
            }}
            labelFormatter={() => ""}
            formatter={(value) => [`$${Number(value).toFixed(2)}`, "Balance"]}
          />
          <Line type="monotone" dataKey="balance" stroke="var(--accent)" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
