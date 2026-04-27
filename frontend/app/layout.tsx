import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import QueryProvider from "@/components/query-provider"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "Indian Stock Analyzer",
  description: "Daily AI-powered NSE stock screener — 30 picks with BUY / HOLD / SELL verdicts",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-gray-100 text-gray-900 antialiased`}>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  )
}
