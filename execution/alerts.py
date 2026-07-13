"""แจ้งเตือนผ่าน Discord webhook — จุดเดียวที่ทำให้รู้ว่าระบบมีปัญหาโดยไม่ต้องเฝ้าคอนโซล

ก่อนหน้านี้ live_runner.py มีแค่ print() เป็น "การแจ้งเตือน" — ถ้า kill-switch ทำงานตอนตี 3 หรือ
MT5 หลุดการเชื่อมต่อ ไม่มีใครรู้เลยจนกว่าจะมาเปิดดู log เอง โมดูลนี้แก้ปัญหานั้นด้วย Discord webhook
(ตั้งค่าง่าย ไม่ต้องมี bot token เต็มรูปแบบ)

วิธีตั้งค่า: สร้าง webhook ใน Discord (Server Settings → Integrations → Webhooks → New Webhook)
แล้วใส่ URL ลง .env เป็น DISCORD_WEBHOOK_URL — ถ้าไม่ตั้งค่า ฟังก์ชันจะ no-op เงียบๆ (ไม่ throw)
เพื่อไม่ให้การแจ้งเตือนพังจนกระทบ trading loop หลัก
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

# ping ซ้ำเรื่องเดิมถี่เกินไปจะรำคาญ/โดน Discord rate-limit — เก็บเวลาแจ้งล่าสุดต่อ key แล้ว
# บล็อกไม่ให้ยิงซ้ำภายในหน้าต่างเวลานี้ (ยกเว้น alert ที่ระบุ dedupe_seconds=0 ให้ยิงทุกครั้ง)
_last_sent: dict[str, float] = {}
DEFAULT_DEDUPE_SECONDS = 300  # 5 นาที


def send_discord_alert(
    message: str,
    webhook_url: str | None,
    level: str = "info",
    dedupe_key: str | None = None,
    dedupe_seconds: int = DEFAULT_DEDUPE_SECONDS,
) -> bool:
    """ส่งข้อความแจ้งเตือนไป Discord — คืน True ถ้าส่งสำเร็จ (หรือถูก dedupe ไว้โดยตั้งใจ)

    level: "info" (ฟ้า) / "warning" (เหลือง) / "critical" (แดง) — กำหนดสี embed ให้เห็นความรุนแรงเร็วๆ
    dedupe_key: ถ้าระบุ จะกันไม่ให้ยิงข้อความ key เดียวกันซ้ำถี่กว่า dedupe_seconds
    ไม่มี webhook_url ตั้งไว้ = no-op เงียบๆ (คืน False) กัน error บาน trading loop หลัก
    """
    if not webhook_url:
        return False

    if dedupe_key is not None:
        now = time.monotonic()
        last = _last_sent.get(dedupe_key)
        if last is not None and now - last < dedupe_seconds:
            return False
        _last_sent[dedupe_key] = now

    colors = {"info": 0x3498DB, "warning": 0xF1C40F, "critical": 0xE74C3C}
    payload = {
        "embeds": [
            {
                "title": f"🥇 AI Trader V2 — {level.upper()}",
                "description": message,
                "color": colors.get(level, colors["info"]),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }

    try:
        import requests

        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.status_code < 300
    except Exception as exc:  # การแจ้งเตือนพังต้องไม่ทำให้ trading loop หลักพังตาม
        print(f"[alerts] ส่ง Discord แจ้งเตือนไม่สำเร็จ: {exc}", flush=True)
        return False
