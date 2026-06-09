import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Account | Indian Stock Analyzer",
}

export default function AccountLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
