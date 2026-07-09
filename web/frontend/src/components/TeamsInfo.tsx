"use client";

import { useEffect, useState } from "react";
import type { StrategyInfo } from "@/lib/api";

export function TeamsInfo() {
  const [teams, setTeams] = useState<StrategyInfo[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch("/api/strategies")
      .then((r) => r.json())
      .then((data: StrategyInfo[]) => setTeams(data))
      .finally(() => setLoaded(true));
  }, []);

  return (
    <details className="mb-6 rounded-xl border border-border bg-surface open:pb-4">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-foreground">
        ℹ️ ทีมทั้งหมดในระบบทำงานยังไงบ้าง ({teams.length || "…"} ทีม)
      </summary>
      <div className="grid grid-cols-1 gap-3 px-4 md:grid-cols-2">
        {!loaded && <p className="text-sm text-muted">กำลังโหลด...</p>}
        {teams.map((team) => (
          <div
            key={team.name}
            className="rounded-lg border border-border bg-surface-2 p-4"
          >
            <div className="mb-2 flex items-center gap-2">
              <span className="rounded bg-accent/15 px-2 py-0.5 text-xs font-semibold text-accent">
                {team.name}
              </span>
            </div>
            <p className="mb-3 text-sm leading-relaxed text-muted">
              {team.description}
            </p>
            {team.committee.length > 0 && (
              <div className="mb-3">
                <p className="mb-1 text-xs font-medium text-foreground">
                  นักเทรดในทีม ({team.committee.length} คน — ค้านได้ไม่เกิน 1 เสียงถึงเข้าไม้):
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {team.committee.map((m) => (
                    <span
                      key={m.name}
                      className="rounded-full border border-border bg-surface px-2 py-0.5 text-xs text-muted"
                      title={m.role}
                    >
                      {m.name} · {m.role}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              {Object.entries(team.params).map(([key, value]) => (
                <span key={key}>
                  <span className="text-foreground">{key}</span>={String(value)}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
