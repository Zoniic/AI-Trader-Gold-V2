import type { RegimeStats } from "@/lib/api";

const REGIME_LABEL: Record<string, string> = {
  trend: "เทรนด์",
  range: "แกว่งกรอบ",
  volatile: "ผันผวนสูง",
  low_volatility: "เงียบผิดปกติ",
  unknown: "ไม่ทราบ",
};

export function RegimeBreakdown({ data }: { data: RegimeStats[] }) {
  if (data.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center rounded-xl border border-border bg-surface text-sm text-muted">
        ยังไม่มีข้อมูลเพียงพอ
      </div>
    );
  }

  return (
    <div className="overflow-auto rounded-xl border border-border bg-surface">
      <table className="w-full text-left text-sm">
        <thead className="bg-surface-2 text-xs text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">สภาวะตลาด</th>
            <th className="px-3 py-2 font-medium">เทรด</th>
            <th className="px-3 py-2 font-medium">Win rate</th>
            <th className="px-3 py-2 font-medium">Profit factor</th>
            <th className="px-3 py-2 font-medium">Expectancy</th>
            <th className="px-3 py-2 font-medium">Total PnL</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r) => (
            <tr key={r.regime} className="border-t border-border">
              <td className="px-3 py-2 text-foreground">
                {REGIME_LABEL[r.regime] ?? r.regime}
              </td>
              <td className="px-3 py-2 text-muted">{r.total_trades}</td>
              <td className="px-3 py-2 text-muted">{r.win_rate_pct.toFixed(1)}%</td>
              <td className="px-3 py-2 text-muted">
                {r.profit_factor === null ? "∞" : r.profit_factor.toFixed(3)}
              </td>
              <td
                className={`px-3 py-2 font-medium ${
                  r.expectancy >= 0 ? "text-profit" : "text-loss"
                }`}
              >
                {r.expectancy.toFixed(2)}
              </td>
              <td
                className={`px-3 py-2 font-medium ${
                  r.total_pnl >= 0 ? "text-profit" : "text-loss"
                }`}
              >
                {r.total_pnl >= 0 ? "+" : ""}
                {r.total_pnl.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
