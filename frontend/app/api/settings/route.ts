import { NextRequest } from "next/server";
import { proxyGet, proxyPut } from "@/lib/backend";

export async function GET() {
  return proxyGet("/api/settings");
}

export async function PUT(req: NextRequest) {
  const body = await req.json();
  return proxyPut("/api/settings", body);
}
