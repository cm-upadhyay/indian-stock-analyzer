/**
 * Server-side helper for forwarding the Auth.js session JWT to the Lambda API.
 *
 * The Auth.js session cookie is an HS256 JWT signed with NEXTAUTH_SECRET — the
 * same secret Lambda uses in _require_user_jwt. Forwarding the raw cookie value
 * avoids re-signing and keeps Lambda's verification path simple.
 *
 * Precedence:
 *   1. Auth.js session cookie → Bearer token (production / signed-in user)
 *   2. X-API-Key env var fallback (local dev when NEXTAUTH_SECRET not configured)
 *   3. Empty (Lambda will open-access when NEXTAUTH_SECRET is also absent)
 */

import { cookies } from "next/headers"

export async function buildAuthHeaders(): Promise<Record<string, string>> {
  const jar = await cookies()

  // Auth.js v5: HTTP cookie in dev, __Secure- prefixed on HTTPS in production
  const token =
    jar.get("next-auth.session-token")?.value ??
    jar.get("__Secure-next-auth.session-token")?.value

  if (token) {
    return { Authorization: `Bearer ${token}` }
  }

  // Local dev without auth configured — API key keeps the proxy working
  const apiKey = process.env.API_KEY
  if (apiKey && !process.env.NEXTAUTH_SECRET) {
    return { "X-API-Key": apiKey }
  }

  return {}
}

/** True when the caller must be authenticated (NEXTAUTH_SECRET is configured). */
export function authRequired(): boolean {
  return Boolean(process.env.NEXTAUTH_SECRET)
}
