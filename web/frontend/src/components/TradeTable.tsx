import type { CommitteeOpinion, Trade } from "@/lib/api";

function fmt(n: number, digits = 2): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function parseDiscussion(raw: string | null): CommitteeOpinion[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function AnalysisCell({
  raw,
  review,
}: {
  raw: string | null;
  review: string | null;
}) {
  const opinions = parseDiscussion(raw);
  if (opinions.length === 0 && !review) {
    return <span className="text-muted">-</span>;
  }
  const dissent = opinions.filter((o) => !o.approve).length;
  const label =
    opinions.length > 0
      ? dissent === 0
        ? "เอกฉันท์ 5/5"
        : `${opinions.length - dissent}/5 (ค้าน ${dissent})`
      : "รีวิว";
  return (
    <details>
      <summary className="cursor-pointer select-none text-xs text-accent">
        {label}
      </summary>
      <div className="mt-1 w-80 rounded-lg border border-border bg-surface-2 p-2 text-xs">
        {opinions.length > 0 && (
          <ul className="space-y-1">
            {opinions.map((o) => (
              <li key={o.member} className="leading-snug">
                <span className={o.approve ? "text-profit" : "text-loss"}>
                  {o.approve ? "✓" : "✗"}
                </span>{" "}
                <span className="text-foreground">{o.member}</span>{" "}
                <span className="text-muted">({o.role}):</span>{" "}
                <span className="text-muted">{o.comment}</span>
              </li>
            ))}
          </ul>
        )}
        {review && (
          <p className="mt-2 border-t border-border pt-2 leading-snug text-accent">
            📋 รีวิวหลังจบไม้: <span className="text-muted">{review}</span>
          </p>
        )}
      </div>
    </details>
  );
}

export function TradeTable({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-border bg-surface text-sm text-muted">
        ยังไม่มีเทรดใน run นี้
      </div>
    );
  }

  // ไม้ที่ยังเปิดอยู่ (exit_time ว่าง) เรียงไว้บนสุดเสมอ ที่เหลือเรียงตามเวลาปิดล่าสุด
  const sorted = [...trades].sort((a, b) => {
    if (a.exit_time == null && b.exit_time == null) return 0;
    if (a.exit_time == null) return -1;
    if (b.exit_time == null) return 1;
    return new Date(b.exit_time).getTime() - new Date(a.exit_time).getTime();
  });

  return (
    <div className="max-h-96 overflow-auto rounded-xl border border-border bg-surface">
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 bg-surface-2 text-xs text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">ทิศทาง</th>
            <th className="px-3 py-2 font-medium">เข้า</th>
            <th className="px-3 py-2 font-medium">SL</th>
            <th className="px-3 py-2 font-medium">TP</th>
            <th className="px-3 py-2 font-medium">ล็อต</th>
            <th className="px-3 py-2 font-medium">ออก</th>
            <th className="px-3 py-2 font-medium">PnL</th>
            <th className="px-3 py-2 font-medium">R</th>
            <th className="px-3 py-2 font-medium">ผล</th>
            <th className="px-3 py-2 font-medium">สภาวะตลาด</th>
            <th className="px-3 py-2 font-medium">มติทีม + รีวิว</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((t) => (
            <tr key={t.id} className="border-t border-border align-top">
              <td className="px-3 py-2">
                <span
                  className={
                    t.direction === "BUY" ? "text-profit" : "text-loss"
                  }
                >
                  {t.direction}
                </span>
              </td>
              <td className="px-3 py-2 text-muted">{fmt(t.entry)}</td>
              <td className="px-3 py-2 text-muted">{fmt(t.sl)}</td>
              <td className="px-3 py-2 text-muted">{fmt(t.tp)}</td>
              <td className="px-3 py-2 text-muted">{fmt(t.lot)}</td>
              <td className="px-3 py-2 text-muted">
                {t.exit_time
                  ? new Date(t.exit_time).toLocaleString("th-TH", {
                      dateStyle: "short",
                      timeStyle: "short",
                    })
                  : <span className="text-accent">ยังเปิดอยู่</span>}
              </td>
              <td
                className={`px-3 py-2 font-medium ${
                  t.pnl == null ? "text-muted" : t.pnl >= 0 ? "text-profit" : "text-loss"
                }`}
              >
                {t.pnl == null ? "-" : `${t.pnl >= 0 ? "+" : ""}${fmt(t.pnl)}`}
              </td>
              <td
                className={`px-3 py-2 font-medium ${
                  (t.pnl_r ?? 0) >= 0 ? "text-profit" : "text-loss"
                }`}
              >
                {t.pnl_r !== null ? `${t.pnl_r >= 0 ? "+" : ""}${t.pnl_r.toFixed(2)}R` : "-"}
              </td>
              <td className="px-3 py-2 text-muted">{t.outcome ?? "-"}</td>
              <td className="px-3 py-2 text-muted">{t.regime ?? "-"}</td>
              <td className="px-3 py-2">
                <AnalysisCell raw={t.discussion} review={t.review} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
