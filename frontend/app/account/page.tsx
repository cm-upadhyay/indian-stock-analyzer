"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { useSession } from "next-auth/react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { fetchMe, fetchLinkCode, unlinkTelegram } from "@/lib/api"

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <button
      onClick={handleCopy}
      className="ml-2 rounded-md border border-gray-200 px-2.5 py-1 text-xs text-gray-500 hover:bg-gray-50"
      aria-label="Copy code to clipboard"
    >
      {copied ? "Copied!" : "Copy"}
    </button>
  )
}

function TelegramSection() {
  const queryClient = useQueryClient()
  const { data: me, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    staleTime: 30_000,
  })

  const [code, setCode] = useState<string | null>(null)
  const [codeExpiry, setCodeExpiry] = useState<number | null>(null)
  const [timeLeft, setTimeLeft] = useState(0)

  // Countdown timer for the link code
  useEffect(() => {
    if (!codeExpiry) return
    const tick = () => setTimeLeft(Math.max(0, codeExpiry - Math.floor(Date.now() / 1000)))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [codeExpiry])

  const generateMutation = useMutation({
    mutationFn: fetchLinkCode,
    onSuccess: (data) => {
      setCode(data.code)
      setCodeExpiry(Math.floor(Date.now() / 1000) + data.expires_in_seconds)
    },
  })

  const unlinkMutation = useMutation({
    mutationFn: unlinkTelegram,
    onSuccess: () => {
      setCode(null)
      queryClient.invalidateQueries({ queryKey: ["me"] })
    },
  })

  if (isLoading) {
    return (
      <div className="h-24 animate-pulse rounded-xl bg-gray-100" aria-busy="true" />
    )
  }

  const isLinked = me?.telegram_linked ?? false
  const username = me?.chat_username ?? ""
  const isPro = me?.subscription_status === "active"

  return (
    <section aria-labelledby="telegram-heading">
      <h2 id="telegram-heading" className="text-base font-semibold text-gray-900">
        Telegram
      </h2>
      <p className="mt-1 text-sm text-gray-500">
        Link your Telegram account to receive stock verdicts via bot.
        {!isPro && (
          <> Free subscribers receive 5 stocks/day. <Link href="/subscribe" className="text-gray-900 underline">Upgrade to Pro</Link> for all verdicts and morning notes.</>
        )}
      </p>

      {isLinked ? (
        <div className="mt-4 flex items-center gap-4 rounded-xl border border-green-200 bg-green-50 px-5 py-4">
          <span className="text-lg" aria-hidden="true">✅</span>
          <div className="flex-1">
            <p className="text-sm font-medium text-green-800">
              Linked{username ? ` as @${username}` : ""}
            </p>
            <p className="text-xs text-green-600">
              {isPro
                ? "Receiving all verdicts and morning follow-ups"
                : "Receiving 5 stocks/day — upgrade for full access"}
            </p>
          </div>
          <button
            onClick={() => unlinkMutation.mutate()}
            disabled={unlinkMutation.isPending}
            className="rounded-md border border-red-200 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
            aria-label="Disconnect Telegram account"
          >
            {unlinkMutation.isPending ? "Unlinking…" : "Disconnect"}
          </button>
        </div>
      ) : (
        <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50 px-5 py-4">
          <p className="text-sm text-gray-700 font-medium">Connect Telegram</p>
          <ol className="mt-3 space-y-2 text-sm text-gray-600 list-decimal list-inside">
            <li>Click <strong>Generate code</strong> below</li>
            <li>Open your Telegram bot and send: <code className="rounded bg-gray-200 px-1">/link &lt;code&gt;</code></li>
          </ol>

          {code && timeLeft > 0 ? (
            <div className="mt-4 flex items-center gap-2">
              <div className="flex items-center rounded-lg border border-gray-300 bg-white px-4 py-2">
                <span className="font-mono text-2xl font-bold tracking-widest text-gray-900">
                  {code}
                </span>
                <CopyButton text={`/link ${code}`} />
              </div>
              <span className="text-xs text-gray-400">
                expires in {Math.floor(timeLeft / 60)}:{String(timeLeft % 60).padStart(2, "0")}
              </span>
            </div>
          ) : (
            <button
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
              className="mt-4 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
            >
              {generateMutation.isPending ? "Generating…" : "Generate code"}
            </button>
          )}

          {generateMutation.isError && (
            <p role="alert" className="mt-2 text-xs text-red-600">
              Failed to generate code. Please try again.
            </p>
          )}
        </div>
      )}
    </section>
  )
}

export default function AccountPage() {
  const { data: session, status } = useSession()
  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: status === "authenticated",
    staleTime: 30_000,
  })

  if (status === "loading") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <p className="text-gray-400" role="status" aria-live="polite">Loading…</p>
      </div>
    )
  }

  if (status === "unauthenticated") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <p className="text-gray-500">Sign in to view your account.</p>
      </div>
    )
  }

  const isPro = me?.subscription_status === "active"

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="mb-8 text-2xl font-bold text-gray-900">Account</h1>

      {/* Profile */}
      <section aria-labelledby="profile-heading" className="mb-8">
        <h2 id="profile-heading" className="text-base font-semibold text-gray-900">Profile</h2>
        <div className="mt-3 space-y-1 text-sm text-gray-600">
          <p><span className="text-gray-400 w-24 inline-block">Name</span>{session?.user?.name ?? "—"}</p>
          <p><span className="text-gray-400 w-24 inline-block">Email</span>{session?.user?.email ?? "—"}</p>
          <p>
            <span className="text-gray-400 w-24 inline-block">Plan</span>
            {isPro ? (
              <span className="rounded-full bg-gray-900 px-2.5 py-0.5 text-xs font-semibold text-white">Pro</span>
            ) : (
              <>
                Free{" "}
                <Link href="/subscribe" className="text-xs text-gray-500 underline hover:text-gray-900">
                  Upgrade →
                </Link>
              </>
            )}
          </p>
        </div>
      </section>

      <hr className="mb-8 border-gray-200" />

      {/* Telegram */}
      <TelegramSection />
    </div>
  )
}
