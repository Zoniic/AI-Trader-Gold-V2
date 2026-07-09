import type { ReviewSummary } from "@/lib/api";

/** บทวิเคราะห์อัตโนมัติระดับ run: สถิติ MAE/MFE + คำแนะนำปรับ SL/TP/partial/snowball */
export function ReviewSummaryCard({ summary }: { summary: ReviewSummary }) {
  if (!summary || summary.total === 0) {
    return null;
  }
  const statItems: { label: string; value: string }[] = [
    { label: "ชนะเฉลี่ย", value: `${(summary.avg_win_r ?? 0) >= 0 ? "+" : ""}${(summary.avg_win_r ?? 0).toFixed(2)}R` },
    { label: "แพ้เฉลี่ย", value: `${(summary.avg_loss_r ?? 0).toFixed(2)}R` },
    { label: "แพ้ทั้งที่เคยกำไร ≥1R", value: `${summary.losses_were_winning_1r ?? 0} ไม้` },
    { label: "แพ้แบบผิดทางทันที", value: `${summary.losses_wrong_entry ?? 0} ไม้` },
    { label: "ชนะแบบ SL ไม่เฉียดเลย", value: `${summary.wins_clean_sl ?? 0} ไม้` },
    { label: "ชน TP แล้ววิ่งต่อ ≥1R", value: `${summary.tp_ran_on_1r ?? 0}/${summary.tp_hits_with_lookahead ?? 0} ไม้` },
  ];
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {statItems.map((s) => (
          <div key={s.label}>
            <p className="text-xs text-muted">{s.label}</p>
            <p className="text-sm font-medium text-foreground">{s.value}</p>
          </div>
        ))}
      </div>
      <ul className="space-y-1.5 border-t border-border pt-3">
        {summary.recommendations.map((rec) => (
          <li key={rec} className="text-sm leading-relaxed text-accent">
            💡 <span className="text-muted">{rec}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
