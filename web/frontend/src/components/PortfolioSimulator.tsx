"use client";

import { useEffect, useState } from "react";
import type { PortfolioData } from "@/lib/api";

const INITIAL_BALANCE = 10000;

/** ตอบคำถาม "อยากได้ X%/เดือน ต้องเร่ง risk เท่าไหร่ และแลกกับ DD/โอกาสเจ๊งเท่าไหร่" ด้วยข้อมูลจริง */
export function PortfolioSimulator() {
  const [data, setData] = useState<PortfolioData | null>(null);

  useEffect(() => {
    fetch("/api/portfolio")
      .then((r) => r.json())
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (!data) return null;
  if (data.error) {
    return (
      <div className="mb-6 rounded-xl border border-loss/40 bg-loss/10 p-4 text-sm text-loss">
        จำลองพอร์ตไม่ได้: {data.error}
      </div>
    );
  }

  return (
    <details className="mb-6 rounded-xl border border-border bg-surface open:pb-4">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-foreground">
        💰 จำลองพอร์ตรวม — ถ้าเอาเงิน ${INITIAL_BALANCE.toLocaleString()} เทรด {data.selections.length} ทีมพร้อมกัน
      </summary>
      <div className="px-4">
        <div className="mb-4 rounded-lg border border-border bg-background p-3 text-xs leading-relaxed text-muted">
          <p className="mb-1.5">
            <strong className="text-foreground">สิ่งที่จำลอง:</strong> เอาเงินก้อนเดียว{" "}
            <strong className="text-foreground">${INITIAL_BALANCE.toLocaleString()}</strong> ให้ทั้ง{" "}
            {data.selections.length} ทีมเทรดพร้อมกัน (ไม่ใช่แยกบัญชีคนละก้อน) แล้ววิ่งย้อนหลังบนข้อมูลจริงทั้งหมด
            — ตัวเลขในตารางคือ <strong className="text-foreground">ผลลัพธ์จริงถ้าทำแบบนี้ในอดีต</strong>
          </p>
          <p>
            แต่ละทีมเสี่ยงเป็น % ของทุนทั้งหมดต่อไม้ (ในวงเล็บ เช่น 1% = เสี่ยงเสียได้สูงสุด 1% ของเงินทั้งก้อนต่อ 1 ไม้
            — lot size คำนวณอัตโนมัติจากระยะ SL ของแต่ละไม้ ไม่ใช่ตัวเลขคงที่):
          </p>
          <p className="mt-1 text-foreground">
            {data.selections.map((s) => `${s.strategy}:${s.timeframe} (${s.risk_pct}%)`).join(" · ")}
          </p>
        </div>

        <div className="mb-3 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-xs text-muted">
          <strong className="text-accent">&quot;ตัวคูณ risk&quot; คืออะไร:</strong> ตัวคูณความเสี่ยงต่อไม้ของทุกทีมพร้อมกัน
          — เช่น 2x หมายถึงทีมที่เคยเสี่ยง 1%/ไม้ จะกลายเป็นเสี่ยง 2%/ไม้ (ได้/เสียเร็วขึ้นเท่าตัว) ยิ่งคูณสูง lot
          size ต่อไม้ก็ใหญ่ขึ้นตาม แต่ DD และโอกาสเจ๊งไม่ได้โตเป็นเส้นตรง — โตเร็วกว่ามาก
        </div>

        <div className="mb-4 overflow-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface-2 text-xs text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">ตัวคูณ risk</th>
                <th className="px-3 py-2 font-medium">
                  ทุนจบ
                  <div className="font-normal normal-case text-[10px] text-muted/70">
                    เริ่ม ${INITIAL_BALANCE.toLocaleString()}
                  </div>
                </th>
                <th className="px-3 py-2 font-medium">
                  Max DD
                  <div className="font-normal normal-case text-[10px] text-muted/70">
                    เงินหล่นลึกสุดจากจุดสูงสุด
                  </div>
                </th>
                <th className="px-3 py-2 font-medium">เดือนเฉลี่ย</th>
                <th className="px-3 py-2 font-medium">เดือนแย่สุด</th>
                <th className="px-3 py-2 font-medium">เดือนดีสุด</th>
                <th className="px-3 py-2 font-medium">
                  เจ๊งไหม
                  <div className="font-normal normal-case text-[10px] text-muted/70">
                    เงินเหลือ &lt;40% ของทุนตั้งต้น
                  </div>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.multiplier_comparison.map((row) => (
                <tr key={row.multiplier} className="border-t border-border">
                  <td className="px-3 py-2 font-medium text-foreground">{row.multiplier}x</td>
                  <td className="px-3 py-2 text-muted">
                    ${row.final_balance.toLocaleString()}
                    <span className="ml-1 text-[10px] text-muted/60">
                      ({row.final_balance >= INITIAL_BALANCE ? "+" : ""}
                      {(((row.final_balance - INITIAL_BALANCE) / INITIAL_BALANCE) * 100).toFixed(0)}%)
                    </span>
                  </td>
                  <td className="px-3 py-2 text-loss">{row.max_drawdown_pct.toFixed(1)}%</td>
                  <td
                    className={`px-3 py-2 font-medium ${
                      row.avg_monthly_return_pct >= 0 ? "text-profit" : "text-loss"
                    }`}
                  >
                    {row.avg_monthly_return_pct >= 0 ? "+" : ""}
                    {row.avg_monthly_return_pct.toFixed(1)}%
                  </td>
                  <td className="px-3 py-2 text-loss">{row.worst_month_pct.toFixed(1)}%</td>
                  <td className="px-3 py-2 text-profit">+{row.best_month_pct.toFixed(1)}%</td>
                  <td className="px-3 py-2">
                    {row.ruined ? (
                      <span className="font-semibold text-loss">ใช่ — เจ๊ง!</span>
                    ) : (
                      <span className="text-profit">ไม่</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs leading-relaxed text-muted">
          ⚠ ตัวคูณสูงให้ผลตอบแทน/เดือนสูงขึ้นจริง แต่ MaxDD และโอกาสเจ๊งพุ่งไม่เป็นเส้นตรง — เป้า
          100-1000%/เดือนพร้อมเงินต้นไม่หายเป็นไปไม่ได้ในทางคณิตศาสตร์ด้วย edge ปัจจุบัน ตัวเลขนี้
          ใช้ตัดสินใจว่าจะรับความเสี่ยงระดับไหนด้วยข้อมูลจริง ไม่ใช่ความรู้สึก
        </p>
      </div>
    </details>
  );
}
