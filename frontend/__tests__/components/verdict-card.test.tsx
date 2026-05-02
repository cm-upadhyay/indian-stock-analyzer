import { render, screen } from "@testing-library/react"
import VerdictCard from "@/components/verdict-card"
import type { Verdict } from "@/lib/schemas"

const BASE: Verdict = {
  symbol: "RELIANCE.NS",
  signal: "BUY",
  confidence: 0.72,
  entry: 1320,
  stop_loss: 1270,
  target: 1450,
  whats_happening: "Breakout above resistance",
  why_it_matters: "Volume confirmation",
  watch_out_for: "RBI meeting risk",
  trader_action: "Enter at market open",
  investor_action: "Add on dips",
}

describe("VerdictCard", () => {
  it("shows symbol without .NS suffix", () => {
    render(<VerdictCard verdict={BASE} />)
    expect(screen.getByText("RELIANCE")).toBeInTheDocument()
  })

  it("shows trade setup when entry is set on BUY", () => {
    render(<VerdictCard verdict={BASE} />)
    expect(screen.getByText(/Entry ₹1,320/)).toBeInTheDocument()
    expect(screen.getByText(/Stop ₹1,270/)).toBeInTheDocument()
    expect(screen.getByText(/Target ₹1,450/)).toBeInTheDocument()
  })

  it("shows no-trade message for HOLD without entry", () => {
    render(<VerdictCard verdict={{ ...BASE, signal: "HOLD", entry: null, stop_loss: null, target: null }} />)
    expect(screen.getByText(/No trade/)).toBeInTheDocument()
  })

  it("shows confidence percentage", () => {
    render(<VerdictCard verdict={BASE} />)
    expect(screen.getByText(/72%/)).toBeInTheDocument()
  })

  it("shows watch_out_for text", () => {
    render(<VerdictCard verdict={BASE} />)
    expect(screen.getByText("RBI meeting risk")).toBeInTheDocument()
  })

  it("shows trader and investor action", () => {
    render(<VerdictCard verdict={BASE} />)
    expect(screen.getByText("Enter at market open")).toBeInTheDocument()
    expect(screen.getByText("Add on dips")).toBeInTheDocument()
  })

  it("handles null entry/stop/target gracefully (shows dash)", () => {
    render(<VerdictCard verdict={{ ...BASE, signal: "SELL", entry: null, stop_loss: null, target: null }} />)
    // SELL with null entry → no trade message
    expect(screen.getByText(/No trade/)).toBeInTheDocument()
  })
})
