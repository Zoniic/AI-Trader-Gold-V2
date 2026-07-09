import { NextResponse } from "next/server";
import { verifySession } from "@/lib/dal";
import { fetchLiveStatus } from "@/lib/api";

export async function GET() {
  const authenticated = await verifySession();
  if (!authenticated) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  try {
    const status = await fetchLiveStatus();
    return NextResponse.json(status);
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
