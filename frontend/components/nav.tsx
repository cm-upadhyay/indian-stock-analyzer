"use client"

import Link from "next/link"
import { signIn, signOut, useSession } from "next-auth/react"

const links = [
  { href: "/", label: "Evening Analysis" },
  { href: "/accuracy", label: "Accuracy" },
]

export default function Nav() {
  const { data: session, status } = useSession()

  return (
    <nav aria-label="Main navigation" className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
        <Link href="/" className="text-sm font-bold text-gray-900">
          Indian Stock Analyzer
        </Link>
        <div className="flex flex-1 gap-4" role="list">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="text-sm text-gray-500 hover:text-gray-900"
              role="listitem"
            >
              {l.label}
            </Link>
          ))}
        </div>
        <div className="flex items-center gap-3">
          {status === "loading" ? null : session ? (
            <>
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
