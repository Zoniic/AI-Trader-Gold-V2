"use client";

import { useEffect, useState } from "react";
import type { CouncilData } from "@/lib/api";

const FOCUS_ICON: Record<string, string> = {
  risk: "🛡️",
  edge: "📉",
  discipline: "⚖️",
  psychology: "🧠",
};

/** สภานักวิเคราะห์ AI 4 มุม อ่านผลรันล่าสุดแล้วชี้จุดที่ต้องแก้ — เตรียมไว้สลับเป็น LLM agent จริงได้โดยไม่แก้ผู้เรียก */
export function CouncilReport() {
  const [data, setData] = useState<CouncilData | null>(null);

  useEffect(() => {
    fetch("/api/council")
      .then((r) => r.json())
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (!data) return null;
  const sections = Object.entries(data);
  if (sections.length === 0) return null;

  return (
    <details className="mb-6 rounded-xl border border-border bg-surface open:pb-4">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-foreground">
        🧑‍⚖️ สภานักวิเคราะห์ AI — Risk / Edge / Discipline / Psychology
      </summary>
      <div className="grid gap-3 px-4 sm:grid-cols-2">
        {sections.map(([key, section]) => (
          <div key={key} className="rounded-lg border border-border bg-surface-2 p-3">
            <h4 className="mb-2 text-sm font-medium text-foreground">
              {FOCUS_ICON[key] ?? "🔎"} {section.focus}
            </h4>
            {section.findings.length === 0 ? (
              <p className="text-xs text-muted">ไม่พบประเด็นผิดปกติในรอบล่าสุด</p>
            ) : (
              <ul className="space-y-1.5">
                {section.findings.map((f, i) => (
                  <li key={i} className="text-xs leading-relaxed text-muted">
                    • {f}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}
