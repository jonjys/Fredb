import { proxyGet } from "@/lib/backend";

export async function GET() {
  return proxyGet("/api/futures/status");
}
