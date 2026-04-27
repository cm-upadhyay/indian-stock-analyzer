import { LatestResponse, LatestResponseSchema } from "./schemas"

export async function fetchLatest(): Promise<LatestResponse> {
  const res = await fetch("/api/latest")
  if (!res.ok) {
    throw new Error(`Failed to fetch: HTTP ${res.status}`)
  }
  const raw = await res.json()
  return LatestResponseSchema.parse(raw)
}
