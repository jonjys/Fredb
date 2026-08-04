import { proxyPost } from "@/lib/backend";

export async function POST() {
  return proxyPost("/api/bot/kill/reset");
}
