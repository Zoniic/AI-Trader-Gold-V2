import { NextResponse } from "next/server";
import { verifySession } from "@/lib/dal";
import { fetchRunDetail } from "@/lib/api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ runId: string }> }
) {
  const authenticated = await verifySession();
  if (!authenticated) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const { runId } = await params;

  try {
    const detail = await fetchRunDetail(runId);
    if (!detail) {
      return NextResponse.json({ error: "not found" }, { status: 404 });
    }
    return NextResponse.json(detail);
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
