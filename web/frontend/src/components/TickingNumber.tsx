"use client";

import { useEffect, useRef, useState } from "react";

/** ตัวเลขที่ไล่นับ (animate) จากค่าเดิมไปค่าใหม่ทุกครั้งที่ value เปลี่ยน — ให้ความรู้สึก "สด"
 * เวลาข้อมูล live poll เข้ามาใหม่ทุก 7 วิ แทนที่ตัวเลขจะกระตุกเปลี่ยนดื้อๆ
 */
export function TickingNumber({
  value,
  prefix = "",
  digits = 2,
  durationMs = 600,
}: {
  value: number;
  prefix?: string;
  digits?: number;
  durationMs?: number;
}) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const from = fromRef.current;
    const to = value;
    if (from === to) return;
    const start = performance.now();

    const step = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      setDisplay(from + (to - from) * eased);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(step);
      } else {
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const sign = display >= 0 ? "+" : "";
  return (
    <span>
      {sign}
      {prefix}
      {display.toFixed(digits)}
    </span>
  );
}
