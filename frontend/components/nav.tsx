"use client"

import Link from "next/link"
import { signIn, signOut, useSession } from "next-auth/react"
import { useQuery } from "@tanstack/react-query"
import { fetchMe } from "@/lib/api"

const links = [
  { href: "/", label: "Evening Analysis" },
  { href: "/accuracy", label: "Accuracy" },
]

export default function Nav() {
  const { data: session, status } = useSession()

  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: status === "authenticated",
    retry: false,
    staleTime: 60_000, // re-fetch at most once per minute
  })

  const isPro = me?.subscription_status === "active"

  return (
    <nav aria-label="Main navigation" className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
        <Link href="/" className="text-sm font-bold text-gray-900">
          Indian Stock Analyzer
        </Link>

        <div className="flex flex-1 gap-4">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="text-sm text-gray-500 hover:text-gray-900"
            >
              {l.label}
            </Link>
          ))}
        </div>

        <div className="flex items-center gap-3">
          {status === "loading" ? null : session ? (
            <>
              {isPro ? (
                <span
                  className="rounded-full bg-gray-900 px-2.5 py-0.5 text-xs font-semibold text-white"
                  aria-label="Pro subscriber"
                >
                  Pro
                </span>
              ) : (
                <Link
                  href="/subscribe"
                  className="text-xs font-medium text-gray-500 hover:text-gray-900"
                  aria-label="Upgrade to Pro"
                >
                  Upgrade
                </Link>
              )}
              <span
                className="hidden text-xs text-gray-500 sm:block"
                aria-label={`Signed in as ${session.user?.name ?? session.user?.email}`}
              >
                {session.user?.name ?? session.user?.email}
              </span>
              <button
                onClick={() => signOut()}
                className="rounded-md border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
                aria-label="Sign out"
              >
                Sign out
              </button>
            </>
          ) : (
            <button
              onClick={() => signIn("google")}
              className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-700"
              aria-label="Sign in with Google"
            >
              Sign in
            </button>
          )}
        </div>
      </div>
    </nav>
  )
}
