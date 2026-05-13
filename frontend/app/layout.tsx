import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import { auth } from "@/auth"
import AuthProvider from "@/components/auth-provider"
import Nav from "@/components/nav"
import QueryProvider from "@/components/query-provider"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: {
    default: "Indian Stock Analyzer",
    template: "%s | Indian Stock Analyzer",
  },
  description:
    "Daily AI-powered NSE stock screener — 30 picks with BUY / HOLD / SELL verdicts, morning follow-ups, and accuracy tracking.",
  openGraph: {
    siteName: "Indian Stock Analyzer",
    type: "website",
  },
  robots: { index: true, follow: true },
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const session = await auth()

  return (
    <html lang="en">
      <body className={`${inter.className} bg-gray-100 text-gray-900 antialiased`}>
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:shadow"
        >
          Skip to main content
        </a>
        <AuthProvider session={session}>
          <QueryProvider>
            <Nav />
            <main id="main-content">{children}</main>
            <footer className="mt-16 border-t border-gray-200 bg-white py-6 text-center">
              <p className="text-xs text-gray-400">
                Indian Stock Analyzer ·{" "}
                <a href="/accuracy" className="underline hover:text-gray-600">
                  Accuracy
                </a>{" "}
                ·{" "}
                <a href="/subscribe" className="underline hover:text-gray-600">
                  Pricing
                </a>{" "}
                ·{" "}
                <a href="/privacy" className="underline hover:text-gray-600">
                  Privacy
                </a>{" "}
                ·{" "}
                <a href="/terms" className="underline hover:text-gray-600">
                  Terms
                </a>{" "}
                ·{" "}
                <a href="/model-card" className="underline hover:text-gray-600">
                  Model Card
                </a>{" "}
                · Not financial advice
              </p>
            </footer>
          </QueryProvider>
        </AuthProvider>
      </body>
    </html>
  )
}
