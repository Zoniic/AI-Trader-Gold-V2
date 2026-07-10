"use client";

import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { PnlCandle } from "@/lib/api";

/** แท่งเทียน (OHLC) ของ balance รวมพอร์ต ต่อชั่วโมงที่มีไม้ปิดจริง — เขียนเองเพราะ recharts
 * ไม่มี candlestick พร้อมใช้: ใช้ BarChart วาด high-low เป็นไส้ตะเกียงบางๆ แล้ววาดตัวแท่ง (open-close)
 * ทับด้วย custom shape เขียว/แดงตามทิศทาง
 */
function Candle(props: {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: PnlCandle;
  yScale?: (v: number) => number;
}) {
  const { x = 0, width = 0, payload, yScale } = props;
  if (!payload || !yScale) return null;
  const { open, high, low, close } = payload;
  const up = close >= open;
  const color = up ? "var(--profit)" : "var(--loss)";
  const bodyTop = yScale(Math.max(open, close));
  const bodyBottom = yScale(Math.min(open, close));
  const bodyHeight = Math.max(1, bodyBottom - bodyTop);
  const wickX = x + width / 2;

  return (
    <g>
      <line x1={wickX} x2={wickX} y1={yScale(high)} y2={yScale(low)} stroke={color} strokeWidth={1.5} />
      <rect x={x} y={bodyTop} width={width} height={bodyHeight} fill={color} rx={1} />
    </g>
  );
}

export function PnlCandleChart({ candles }: { candles: PnlCandle[] }) {
  if (candles.length === 0) {
    return (
      <div className="flex h-56 items-center justify-center rounded-xl border border-border bg-surface text-sm text-muted">
        ยังไม่มีไม้ปิดพอจะวาดแท่งเทียน (แบ่งแท่งตามชั่วโมงที่มีไม้ปิด)
      </div>
    );
  }

  const allValues = candles.flatMap((c) => [c.high, c.low]);
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const pad = (max - min) * 0.1 || 1;
  const domain: [number, number] = [min - pad, max + pad];

  const data = candles.map((c) => ({
    ...c,
    label: new Date(c.time).toLocaleString("th-TH", { dateStyle: "short", timeStyle: "short" }),
  }));

  return (
    <div className="h-56 rounded-xl border border-border bg-surface p-4">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis tick={{ fill: "var(--muted)", fontSize: 11 }} domain={domain} />
          <Tooltip
            contentStyle={{
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--foreground)",
              fontSize: 12,
            }}
            formatter={(_value, _name, item) => {
              const p = item?.payload as PnlCandle | undefined;
              if (!p) return ["-", ""];
              return [
                `O ${p.open.toFixed(2)} H ${p.high.toFixed(2)} L ${p.low.toFixed(2)} C ${p.close.toFixed(2)}`,
                "Balance",
              ];
            }}
          />
          <Bar
            dataKey="high"
            background={{ fill: "transparent" }}
            shape={(shapeProps: unknown) => {
              const p = shapeProps as {
                x: number;
                width: number;
                payload: PnlCandle;
                background?: { y: number; height: number };
              };
              // แปลงพิกัดจาก recharts (ที่ให้มาเป็นตำแหน่งของค่า "high") ให้เป็นฟังก์ชัน scale
              // เชิงเส้นระหว่าง domain กับพื้นที่วาดจริง (ใช้ background rect ที่ recharts คำนวณมาให้
              // เป็นกรอบเต็มความสูงของ chart area เพื่อ derive scale)
              const bg = p.background;
              if (!bg) return null;
              const [dMin, dMax] = domain;
              const yScale = (v: number) =>
                bg.y + bg.height - ((v - dMin) / (dMax - dMin)) * bg.height;
              return <Candle x={p.x} width={p.width} payload={p.payload} yScale={yScale} />;
            }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
