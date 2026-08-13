// app/api/autotune/status/route.ts
import { proxyGet } from "@/lib/backend";

export async function GET() {
  return proxyGet("/api/autotune/status");
}
