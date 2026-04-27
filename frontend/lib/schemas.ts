import { z } from "zod"

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

export type Verdict = z.infer<typeof VerdictSchema>
export type LatestResponse = z.infer<typeof LatestResponseSchema>
