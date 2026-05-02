import { render, screen } from "@testing-library/react"
import SignalBadge from "@/components/signal-badge"

describe("SignalBadge", () => {
  it("renders BUY signal", () => {
    render(<SignalBadge signal="BUY" />)
    expect(screen.getByText(/BUY/)).toBeInTheDocument()
    expect(screen.getByLabelText("Signal: BUY")).toBeInTheDocument()
  })

  it("renders HOLD signal", () => {
    render(<SignalBadge signal="HOLD" />)
    expect(screen.getByText(/HOLD/)).toBeInTheDocument()
  })

  it("renders SELL signal", () => {
    render(<SignalBadge signal="SELL" />)
    expect(screen.getByText(/SELL/)).toBeInTheDocument()
  })
})
