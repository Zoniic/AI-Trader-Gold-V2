"""Entrypoint: เรียกสภานักวิเคราะห์ (analysis/council.py) สรุปผลรอบล่าสุดทุกทีม

ใช้งาน: python run_analysis.py — แนะนำให้รันทุกสัปดาห์ (SOP ข้อ 6: ประชุมทุกสัปดาห์)
"""
from __future__ import annotations

from analysis.council import run_council
from config import load_settings


def main() -> None:
    settings = load_settings()
    report = run_council(settings.log_db_path)

    print("=== สภานักวิเคราะห์ AI — สรุปประจำรอบ ===\n")
    for name, section in report.items():
        print(f"👤 {name} ({section['focus']})")
        for finding in section["findings"]:
            print(f"   - {finding}")
        print()


if __name__ == "__main__":
    main()
