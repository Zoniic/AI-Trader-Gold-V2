import { NextRequest, NextResponse } from "next/server";
import { verifySession } from "@/lib/dal";
import { fetchLiveCandles } from "@/lib/api";

export async function GET(req: NextRequest) {
  const authenticated = await verifySession();
  if (!authenticated) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  try {
    const symbol = req.nextUrl.searchParams.get("symbol") ?? "GOLD";
    const timeframe = req.nextUrl.searchParams.get("timeframe") ?? "M30";
    const data = await fetchLiveCandles(symbol, timeframe);
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
