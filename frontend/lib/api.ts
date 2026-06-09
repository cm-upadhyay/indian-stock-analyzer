import {
  AccuracyResponse,
  AccuracyResponseSchema,
  LatestResponse,
  LatestResponseSchema,
  LinkCodeResponse,
  LinkCodeResponseSchema,
  Me,
  MeSchema,
  MorningResponse,
  MorningResponseSchema,
  StockResponse,
  StockResponseSchema,
} from "./schemas"

export class AuthError extends Error {
  constructor() {
    super("Unauthorized")
    this.name = "AuthError"
  }
}

export class PaywallError extends Error {
  constructor() {
    super("Payment required")
    this.name = "PaywallError"
  }
}

async function apiFetch(path: string, init?: RequestInit): Promise<unknown> {
  const res = await fetch(path, init)
  if (res.status === 401) throw new AuthError()
  if (res.status === 402) throw new PaywallError()
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

export async function fetchLinkCode(): Promise<LinkCodeResponse> {
  return LinkCodeResponseSchema.parse(await apiFetch("/api/link-code", { method: "POST" }))
}

export async function unlinkTelegram(): Promise<void> {
  await apiFetch("/api/unlink-telegram", { method: "DELETE" })
}
