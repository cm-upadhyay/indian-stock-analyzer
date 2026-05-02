import { render, screen } from "@testing-library/react"
import MorningCard from "@/components/morning-card"
import type { MorningNote } from "@/lib/schemas"

const BASE: MorningNote = {
  symbol: "TCS.NS",
  company_name: "Tata Consultancy Services",
  previous_signal: "BUY",
  status: "INTACT",
  morning_text: "Signal remains intact. Price held above support.",
}

describe("MorningCard", () => {
  it("shows symbol without .NS suffix", () => {
    render(<MorningCard note={BASE} />)
    expect(screen.getByText("TCS")).toBeInTheDocument()
  })

  it("shows status badge for INTACT", () => {
    render(<MorningCard note={BASE} />)
    expect(screen.getByLabelText("Status: INTACT")).toBeInTheDocument()
  })

  it("shows status badge for STRENGTHENED", () => {
    render(<MorningCard note={{ ...BASE, status: "STRENGTHENED" }} />)
    expect(screen.getByLabelText("Status: STRENGTHENED")).toBeInTheDocument()
  })

  it("shows status badge for WEAKENED", () => {
    render(<MorningCard note={{ ...BASE, status: "WEAKENED" }} />)
    expect(screen.getByLabelText("Status: WEAKENED")).toBeInTheDocument()
  })

  it("shows morning text", () => {
    render(<MorningCard note={BASE} />)
    expect(screen.getByText("Signal remains intact. Price held above support.")).toBeInTheDocument()
  })

  it("shows previous signal", () => {
    render(<MorningCard note={BASE} />)
    expect(screen.getByText(/BUY/)).toBeInTheDocument()
  })
})
