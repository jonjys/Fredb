import { proxyGet } from "@/lib/backend";

export async function GET(request: Request, { params }: { params: { id: string } }) {
  const limit = new URL(request.url).searchParams.get("limit") ?? "60";
  return proxyGet(`/api/positions/${params.id}/candles?limit=${limit}`);
}
