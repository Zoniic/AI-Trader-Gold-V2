# Dashboard เว็บ (FastAPI + Next.js) — ดูผลเทรดผ่าน LAN

ทางเลือกที่สอง (นอกจาก [dashboard.py](../dashboard.py) แบบ Streamlit) — ทำเป็นเว็บแยก 2 ส่วน
เพื่อ UI ที่ปรับแต่งเองได้เต็มที่ และให้คนอื่นในวง LAN เดียวกันเข้าดูผ่านเบราว์เซอร์ได้

## สถาปัตยกรรม

```
Browser (เครื่องไหนก็ได้ในวง LAN)
        │  http://<LAN IP>:3000
        ▼
web/frontend  (Next.js — public-facing, มีรหัสผ่านกันคนนอก)
        │  http://127.0.0.1:8000  (เรียกจากฝั่ง server เท่านั้น ไม่ใช่ browser)
        ▼
web/backend   (FastAPI — internal, bind 127.0.0.1 เท่านั้น)
        │
        ▼
trading_log.db (SQLite — ไฟล์เดียวกับที่ run_backtest.py เขียน)
```

`web/backend` **ห้าม bind 0.0.0.0** เด็ดขาด เพราะไม่มีการเช็ครหัสผ่านเลย (พึ่งพาเลเยอร์
Next.js อย่างเดียว) — ถ้าเปิด backend สู่ LAN โดยตรงจะข้ามชั้นรหัสผ่านไปเลย

## วิธีรัน

**1. Backend (FastAPI) — รันจาก root ของโปรเจกต์ `AI Trader V2`:**
```bash
pip install -r web/backend/requirements.txt
uvicorn web.backend.main:app --host 127.0.0.1 --port 8000
```

**2. Frontend (Next.js) — รันจาก `web/frontend`:**
```bash
cd web/frontend
npm install
copy .env.local.example .env.local   # แล้วแก้ DASHBOARD_PASSWORD + สร้าง SESSION_SECRET ใหม่
npm run dev
```

สร้าง `SESSION_SECRET` ใหม่ด้วย:
```bash
node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
```

## เข้าจากเครื่องอื่นในวง LAN

`npm run dev` เปิดที่ `0.0.0.0:3000` โดยอัตโนมัติ ตอนรันจะเห็นบรรทัด `Network: http://<LAN IP>:3000`
ในเครื่องอื่นที่อยู่วงเดียวกัน (Wi-Fi/สาย LAN เดียวกัน) เปิดเบราว์เซอร์ไปที่ URL นั้นได้เลย
ไม่ต้อง forward port หรือ deploy ขึ้น cloud ใด ๆ

## รหัสผ่าน + ความปลอดภัย

- ตั้งรหัสผ่านที่ `DASHBOARD_PASSWORD` ใน `web/frontend/.env.local`
- Session cookie เป็น httpOnly + signed (jose/JWT) อายุ 7 วัน เก็บแค่ flag "authenticated" ไม่มีข้อมูลอ่อนไหวอยู่ในนั้น
- **ข้อจำกัดที่ควรรู้:** เป็น HTTP ธรรมดา (ไม่มี HTTPS) เหมาะกับ LAN ที่เชื่อถือได้เท่านั้น
  ถ้าจะเปิดสู่อินเทอร์เน็ตสาธารณะในอนาคต ต้องเพิ่ม HTTPS (reverse proxy เช่น Caddy/nginx)
  และพิจารณาใช้ auth library จริงจัง (ดูรายชื่อใน Next.js docs) แทนรหัสผ่านเดี่ยวนี้

## โครงสร้างไฟล์

```
web/
├── backend/
│   ├── main.py              FastAPI: GET /runs, GET /runs/{run_id}
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── proxy.ts          เช็ค session cookie ก่อนเข้าทุกหน้า (ยกเว้น /login)
    │   ├── lib/
    │   │   ├── session.ts     encrypt/decrypt/createSession (jose)
    │   │   ├── dal.ts         verifySession() — เรียกซ้ำในทุก route handler
    │   │   └── api.ts         fetch ไปหา FastAPI backend (server-only)
    │   ├── app/
    │   │   ├── actions/auth.ts   Server Actions: login/logout
    │   │   ├── login/page.tsx
    │   │   ├── page.tsx           หน้า dashboard หลัก (เช็ค session ก่อน render)
    │   │   └── api/runs/...       route handlers proxy ไป backend
    │   └── components/
    │       ├── Dashboard.tsx      client component: polling ทุก 5 วิ
    │       ├── MetricCard.tsx
    │       ├── EquityChart.tsx    recharts
    │       └── TradeTable.tsx
    └── .env.local (ไม่ commit)
```

## ทำไมแยก 2 เซิร์ฟเวอร์แทนที่จะให้ Next.js เรียก SQLite ตรง ๆ

Next.js (Node.js) อ่าน SQLite ตรงได้เหมือนกัน แต่แยกไว้เป็น FastAPI ภายในเพราะ:
- ใช้โค้ด query เดิมจาก `persistence/db.py` ได้เลย ไม่ต้องเขียน query ซ้ำเป็นภาษาที่สอง
- ถ้าวันหนึ่งมี live runner (Python) เขียนแบบ real-time ลง DB, backend ตัวเดียวกันนี้ต่อยอด
  เป็น WebSocket/SSE endpoint ให้ frontend ได้โดยไม่ต้องเปลี่ยนสถาปัตยกรรม

## "Realtime" หมายถึงอะไรตอนนี้

เหมือนกับ Streamlit dashboard — ยังไม่มี live runner เทรดต่อเนื่อง ข้อมูลขยับเมื่อมีคนรัน
`run_backtest.py`/`run_walkforward.py` ใหม่เท่านั้น หน้าเว็บนี้แค่ poll ทุก 5 วินาทีให้เห็นค่าล่าสุด
เสมอ — ปิด/เปิด auto-refresh ได้จาก checkbox มุมขวาบน
