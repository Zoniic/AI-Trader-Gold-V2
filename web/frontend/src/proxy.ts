import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { decrypt } from "@/lib/session";

// หมายเหตุ: Next.js 16 เปลี่ยนชื่อ middleware.ts -> proxy.ts (พฤติกรรมเดิม)
// นี่คือ optimistic check เท่านั้น — ทุก route handler ใน app/api ต้องเช็ค
// verifySession() ของตัวเองซ้ำเสมอ ห้ามพึ่ง proxy อย่างเดียว

const PUBLIC_PATHS = ["/login"];

export default async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isPublicPath = PUBLIC_PATHS.includes(pathname);

  const token = request.cookies.get("session")?.value;
  const authenticated = await decrypt(token);

  if (!isPublicPath && !authenticated) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (isPublicPath && authenticated) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
