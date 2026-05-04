import { z } from "zod"

// ── Evening analysis ──────────────────────────────────────────────────────────

export const VerdictSchema = z.object({
  symbol: z.string(),
  signal: z.enum(["BUY", "HOLD", "SELL"]),
  confidence: z.number(),
  entry: z.number().int().nullable(),
  stop_loss: z.number().int().nullable(),
  target: z.number().int().nullable(),
  whats_happening: z.string(),
  why_it_matters: z.string(),
  watch_out_for: z.string(),
  trader_action: z.string(),
  investor_action: z.string(),
})

export const LatestResponseSchema = z.object({
  date: z.string(),
  count: z.number().int(),
  analyses: z.array(VerdictSchema),
})

// ── Morning follow-up ─────────────────────────────────────────────────────────

export const MorningNoteSchema = z.object({
  symbol: z.string(),
  company_name: z.string(),
  previous_signal: z.string(),
  status: z.enum(["INTACT", "STRENGTHENED", "WEAKENED"]),
  morning_text: z.string(),
})

export const MorningResponseSchema = z.object({
  date: z.string(),
  count: z.number().int(),
  notes: z.array(MorningNoteSchema),
})

// ── Accuracy ─────────────────────────────────────────────────────────────────

export const AccuracyBySignalSchema = z.object({
  total: z.number().int(),
  correct: z.number().int(),
  accuracy_pct: z.number(),
})

export const AccuracyResponseSchema = z.object({
  period_days: z.number().int(),
  total: z.number().int(),
  correct: z.number().int(),
  accuracy_pct: z.number(),
  target_hit_pct: z.number(),
  stop_triggered_pct: z.number(),
  by_signal: z.record(AccuracyBySignalSchema),
})

// ── Stock detail ──────────────────────────────────────────────────────────────

export const StockResponseSchema = z.object({
  date: z.string(),
  symbol: z.string(),
  found: z.boolean(),
  verdict: VerdictSchema.nullable(),
})

// ── User / subscription ───────────────────────────────────────────────────────

export const MeSchema = z.object({
  user_id: z.string(),
  email: z.string(),
  name: z.string(),
  subscription_status: z.enum(["free", "active", "lapsed", "cancelled"]),
})

// ── Types ─────────────────────────────────────────────────────────────────────

export type Verdict = z.infer<typeof VerdictSchema>
export type LatestResponse = z.infer<typeof LatestResponseSchema>
export type MorningNote = z.infer<typeof MorningNoteSchema>
export type MorningResponse = z.infer<typeof MorningResponseSchema>
export type AccuracyResponse = z.infer<typeof AccuracyResponseSchema>
export type StockResponse = z.infer<typeof StockResponseSchema>
export type Me = z.infer<typeof MeSchema>
