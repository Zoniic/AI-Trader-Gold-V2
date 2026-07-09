import { NextResponse } from "next/server";
import { verifySession } from "@/lib/dal";
import { fetchRegimeChampions } from "@/lib/api";

export async function GET() {
  const authenticated = await verifySession();
  if (!authenticated) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  try {
    const data = await fetchRegimeChampions();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
