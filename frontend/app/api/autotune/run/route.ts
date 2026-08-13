// app/api/autotune/run/route.ts
import { proxyPost } from "@/lib/backend";

export async function POST() {
  return proxyPost("/api/autotune/run");
}
