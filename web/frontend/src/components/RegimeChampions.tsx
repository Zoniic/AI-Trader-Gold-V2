"use client";

import { useEffect, useState } from "react";
import type { RegimeChampionsData } from "@/lib/api";

const REGIME_LABEL: Record<string, string> = {
  trend: "📈 เทรนด์",
  range: "↔️ แกว่งกรอบ",
  volatile: "⚡ ผันผวนสูง",
  low_volatility: "😴 เงียบผิดปกติ",
};

const REGIME_ORDER = ["trend", "range", "volatile", "low_volatility"];

/** แผนที่ "สภาวะกราฟแบบไหน ควรใช้ทีมไหนเทรด" — จากผลรันล่าสุดของแต่ละ (ทีม, TF) */
export function RegimeChampions() {
  const [data, setData] = useState<RegimeChampionsData | null>(null);

  useEffect(() => {
    fetch("/api/regime-champions")
      .then((r) => r.json())
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (!data || data.champions.length === 0) return null;

  const timeframes = [...new Set(data.champions.map((c) => c.timeframe))].sort();

  return (
    <div className="mb-6">
      <h2 className="mb-2 text-sm font-medium text-muted">
        🗺️ กราฟแบบไหน ควรใช้ทีมไหนเทรด (จากผลรันล่าสุดต่อทีมต่อ TF · ขั้นต่ำ 15 ไม้/ช่อง)
      </h2>
      <div className="space-y-3">
        {timeframes.map((tf) => (
          <div key={tf}>
            <p className="mb-1.5 text-xs font-semibold text-foreground">Timeframe {tf}</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {REGIME_ORDER.map((regime) => {
                const cell = data.champions.find(
                  (c) => c.timeframe === tf && c.regime === regime
                );
                if (!cell) return null;
                return (
                  <div
                    key={regime}
                    className="rounded-xl border border-border bg-surface p-3"
                  >
                    <p className="mb-1 text-xs text-muted">{REGIME_LABEL[regime]}</p>
                    {cell.champion ? (
                      <>
                        <p
                          className={`text-sm font-semibold ${
                            cell.profitable ? "text-profit" : "text-loss"
                          }`}
                        >
                          🏆 {cell.champion}
                          {!cell.profitable && " (ขาดทุนน้อยสุด)"}
                        </p>
                        <p className="mt-0.5 text-xs text-muted">
                          {cell.total_pnl! >= 0 ? "+" : ""}
                          {cell.total_pnl!.toFixed(0)} USD · exp{" "}
                          {cell.expectancy!.toFixed(1)} · ชนะ {cell.win_rate_pct!.toFixed(0)}% ·{" "}
                          {cell.total_trades} ไม้
                        </p>
                        {cell.runner_up && (
                          <p className="mt-0.5 text-xs text-muted">
                            รอง: {cell.runner_up}
                          </p>
                        )}
                      </>
                    ) : (
                      <p className="text-xs text-muted">{cell.note}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
