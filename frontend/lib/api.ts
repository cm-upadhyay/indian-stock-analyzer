import {
  AccuracyResponse,
  AccuracyResponseSchema,
  LatestResponse,
  LatestResponseSchema,
  Me,
  MeSchema,
  MorningResponse,
  MorningResponseSchema,
  StockResponse,
  StockResponseSchema,
} from "./schemas"

async function apiFetch(path: string): Promise<unknown> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function fetchLatest(): Promise<LatestResponse> {
  return LatestResponseSchema.parse(await apiFetch("/api/latest"))
}

export async function fetchMorning(): Promise<MorningResponse> {
  return MorningResponseSchema.parse(await apiFetch("/api/morning"))
}

export async function fetchAccuracy(): Promise<AccuracyResponse> {
  return AccuracyResponseSchema.parse(await apiFetch("/api/accuracy"))
}

export async function fetchStock(symbol: string): Promise<StockResponse> {
  return StockResponseSchema.parse(await apiFetch(`/api/stock/${encodeURIComponent(symbol)}`))
}

export async function fetchMe(): Promise<Me> {
  return MeSchema.parse(await apiFetch("/api/me"))
}
