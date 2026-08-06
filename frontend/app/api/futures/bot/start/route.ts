import { proxyPost } from "@/lib/backend";

export async function POST() {
  return proxyPost("/api/futures/bot/start");
}
