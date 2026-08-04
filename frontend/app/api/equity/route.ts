import { proxyGet } from "@/lib/backend";

export async function GET() {
  return proxyGet("/api/equity_history?limit=200");
}
