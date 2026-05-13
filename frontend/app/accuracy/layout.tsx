import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Accuracy | Indian Stock Analyzer",
}

export default function AccuracyLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
