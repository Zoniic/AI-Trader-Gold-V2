"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  createSeriesMarkers,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { LiveCandles } from "@/lib/api";

const REFRESH_MS = 15000; // กราฟราคา refresh ทุก 15 วิ (backend ดึง MT5 สดถ้ามี terminal)
const TIMEFRAMES = ["M30", "H1"] as const;

/**
 * กราฟแท่งเทียนสไตล์ TradingView (ใช้ lightweight-charts ของ TradingView เอง)
 * - แท่งเทียนราคาจริงของ symbol ที่เลือก
 * - ลูกศร ▲▼ จุดที่ทีมเข้าไม้ (เขียว BUY / แดง SELL พร้อมชื่อทีม) + วงกลมจุดปิดไม้ (สี = กำไร/ขาดทุน)
 * - เส้นระดับ entry/SL/TP ของไม้ที่ยังเปิดอยู่
 */
export function PriceChart({ symbols }: { symbols: string[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLinesRef = useRef<ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]>([]);
  const firstLoadRef = useRef(true);

  const [symbol, setSymbol] = useState(symbols[0] ?? "GOLD");
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>("M30");
  const [source, setSource] = useState<string>("");
  const [error, setError] = useState<string>("");

  // สร้าง chart ครั้งเดียว + resize ตาม container
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: "#94a3b8",
        fontSize: 11,
        attributionLogo: true, // ให้เครดิต TradingView ตามเงื่อนไข license
      },
      grid: {
        vertLines: { color: "rgba(51, 65, 85, 0.3)" },
        horzLines: { color: "rgba(51, 65, 85, 0.3)" },
      },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#334155" },
      rightPriceScale: { borderColor: "#334155" },
      crosshair: { mode: 0 },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22C55E",
      downColor: "#EF4444",
      borderUpColor: "#22C55E",
      borderDownColor: "#EF4444",
      wickUpColor: "#22C55E",
      wickDownColor: "#EF4444",
    });
    chartRef.current = chart;
    seriesRef.current = series;
    markersRef.current = createSeriesMarkers(series, []);
    return () => {
      markersRef.current = null;
      seriesRef.current = null;
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // โหลด/refresh ข้อมูล — เปลี่ยน symbol/TF = โหลดใหม่ + fitContent, refresh ปกติไม่รีเซ็ตมุมมอง
  useEffect(() => {
    firstLoadRef.current = true;
    let cancelled = false;

    const load = async () => {
      try {
        const res = await fetch(
          `/api/live/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`,
        );
        if (!res.ok) throw new Error(`โหลดกราฟไม่สำเร็จ (${res.status})`);
        const data: LiveCandles = await res.json();
        if (cancelled || !seriesRef.current || !chartRef.current) return;

        seriesRef.current.setData(
          data.candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })),
        );
        markersRef.current?.setMarkers(
          data.markers.map((m) => ({
            time: m.time as UTCTimestamp,
            position: m.position === "aboveBar" ? "aboveBar" : "belowBar",
            shape: m.shape,
            color: m.color,
            text: m.text,
            size: 1,
          })),
        );

        // เส้น entry/SL/TP ของไม้ที่เปิดอยู่ — ลบชุดเก่าก่อนวาดใหม่ทุกรอบ
        for (const line of priceLinesRef.current) seriesRef.current.removePriceLine(line);
        priceLinesRef.current = [];
        for (const ol of data.open_lines) {
          const specs: { price: number | null; color: string; title: string; style: LineStyle }[] = [
            { price: ol.entry, color: "#3B82F6", title: `${ol.team} ${ol.direction}`, style: LineStyle.Solid },
            { price: ol.sl, color: "#EF4444", title: "SL", style: LineStyle.Dashed },
            { price: ol.tp, color: "#22C55E", title: "TP", style: LineStyle.Dashed },
          ];
          for (const s of specs) {
            if (s.price == null) continue;
            priceLinesRef.current.push(
              seriesRef.current.createPriceLine({
                price: s.price, color: s.color, lineWidth: 1, lineStyle: s.style,
                axisLabelVisible: true, title: s.title,
              }),
            );
          }
        }

        if (firstLoadRef.current) {
          chartRef.current.timeScale().fitContent();
          firstLoadRef.current = false;
        }
        setSource(data.source);
        setError("");
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "โหลดกราฟไม่สำเร็จ");
      }
    };

    load();
    const interval = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [symbol, timeframe]);

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">กราฟราคา + จุดเข้าไม้ของทีม</span>
          {source && (
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                source === "mt5" ? "bg-profit/15 text-profit" : "bg-border/60 text-muted"
              }`}
              title={source === "mt5" ? "ราคาสดจาก MT5" : "ราคาจาก cache ล่าสุด (MT5 ไม่ตอบ)"}
            >
              {source === "mt5" ? "LIVE" : "CACHE"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {symbols.length > 1 &&
            symbols.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSymbol(s)}
                className={`cursor-pointer rounded-lg px-2.5 py-1 text-xs font-medium transition-colors duration-150 ${
                  symbol === s
                    ? "bg-accent/20 text-accent"
                    : "text-muted hover:bg-border/40 hover:text-foreground"
                }`}
              >
                {s}
              </button>
            ))}
          <span className="mx-1 h-4 w-px bg-border" aria-hidden />
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              className={`cursor-pointer rounded-lg px-2.5 py-1 text-xs font-medium transition-colors duration-150 ${
                timeframe === tf
                  ? "bg-accent/20 text-accent"
                  : "text-muted hover:bg-border/40 hover:text-foreground"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>
      {error ? (
        <div className="flex h-[380px] items-center justify-center text-sm text-loss">{error}</div>
      ) : (
        <div ref={containerRef} className="h-[380px] w-full" />
      )}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-muted">
        <span><span className="text-profit">▲</span> ทีมเข้า BUY</span>
        <span><span className="text-loss">▼</span> ทีมเข้า SELL</span>
        <span>● จุดปิดไม้ (เขียว=กำไร แดง=ขาดทุน)</span>
        <span>เส้นทึบน้ำเงิน=entry ไม้ที่เปิดอยู่ · เส้นประ แดง=SL เขียว=TP</span>
      </div>
    </div>
  );
}
