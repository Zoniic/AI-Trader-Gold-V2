import { NextResponse } from "next/server";
import { verifySession } from "@/lib/dal";
import { fetchRuns } from "@/lib/api";

export async function GET() {
  const authenticated = await verifySession();
  if (!authenticated) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  try {
    const runs = await fetchRuns();
    return NextResponse.json(runs);
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
