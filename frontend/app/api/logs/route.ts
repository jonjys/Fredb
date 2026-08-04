import { proxyGet } from "@/lib/backend";

export async function GET() {
  return proxyGet("/api/logs?limit=200");
}
