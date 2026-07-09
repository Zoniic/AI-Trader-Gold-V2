import type { RunSummary } from "@/lib/api";

const MEDALS = ["🥇", "🥈", "🥉"];

/** ตารางแข่งขัน: ผลรันล่าสุดของแต่ละทีม เรียงตาม expectancy (กำไรคาดหวังต่อไม้) */
export function LeagueTable({
  runs,
  onSelectRun,
}: {
  runs: RunSummary[];
  onSelectRun: (runId: string) => void;
}) {
  // runs เรียง started_at ล่าสุดก่อนอยู่แล้ว — เก็บ run แรกที่เจอของแต่ละคู่ (ทีม, TF)
  const latestByTeamTf = new Map<string, RunSummary>();
  for (const run of runs) {
    const key = `${run.strategy}|${run.timeframe ?? "H1"}`;
    if (!latestByTeamTf.has(key)) {
      latestByTeamTf.set(key, run);
    }
  }
  const standings = [...latestByTeamTf.values()].sort(
    (a, b) => (b.expectancy ?? -Infinity) - (a.expectancy ?? -Infinity)
  );

  if (standings.length === 0) return null;

  return (
    <div className="mb-6">
      <h2 className="mb-2 text-sm font-medium text-muted">
        🏆 ตารางแข่งขัน (ผลรันล่าสุดของแต่ละทีม เรียงตาม expectancy)
      </h2>
      <div className="overflow-auto rounded-xl border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface-2 text-xs text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">อันดับ</th>
              <th className="px-3 py-2 font-medium">ทีม</th>
              <th className="px-3 py-2 font-medium">TF</th>
              <th className="px-3 py-2 font-medium">เทรด</th>
              <th className="px-3 py-2 font-medium">Win rate</th>
              <th className="px-3 py-2 font-medium">Profit factor</th>
              <th className="px-3 py-2 font-medium">Expectancy</th>
              <th className="px-3 py-2 font-medium">Balance</th>
              <th className="px-3 py-2 font-medium">สถานะ</th>
            </tr>
          </thead>
          <tbody>
            {standings.map((run, i) => (
              <tr
                key={`${run.strategy}|${run.timeframe ?? "H1"}`}
                className="cursor-pointer border-t border-border hover:bg-surface-2"
                onClick={() => onSelectRun(run.run_id)}
                title="คลิกเพื่อดูรายละเอียด run นี้"
              >
                <td className="px-3 py-2">{MEDALS[i] ?? `${i + 1}`}</td>
                <td className="px-3 py-2 font-medium text-foreground">
                  {run.strategy}
                </td>
                <td className="px-3 py-2 text-muted">{run.timeframe ?? "-"}</td>
                <td className="px-3 py-2 text-muted">{run.total_trades ?? "-"}</td>
                <td className="px-3 py-2 text-muted">
                  {run.win_rate_pct !== null ? `${run.win_rate_pct.toFixed(1)}%` : "-"}
                </td>
                <td className="px-3 py-2 text-muted">
                  {run.profit_factor !== null ? run.profit_factor.toFixed(3) : "-"}
                </td>
                <td
                  className={`px-3 py-2 font-medium ${
                    (run.expectancy ?? 0) >= 0 ? "text-profit" : "text-loss"
                  }`}
                >
                  {run.expectancy !== null ? run.expectancy.toFixed(2) : "-"}
                </td>
                <td className="px-3 py-2 text-muted">
                  {run.final_balance !== null ? `$${run.final_balance.toFixed(0)}` : "-"}
                </td>
                <td className="px-3 py-2 text-xs">
                  {run.halted_at ? (
                    <span className="text-loss">⚠ โดน kill-switch</span>
                  ) : (
                    <span className="text-profit">รันจบปกติ</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
