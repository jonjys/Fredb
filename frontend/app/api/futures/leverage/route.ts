import { NextRequest } from "next/server";
import { proxyPut } from "@/lib/backend";

export async function PUT(req: NextRequest) {
  const body = await req.json();
  return proxyPut("/api/futures/leverage", body);
}
