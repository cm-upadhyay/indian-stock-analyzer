import NextAuth from "next-auth"
import Google from "next-auth/providers/google"
import { SignJWT, jwtVerify } from "jose"
import type { JWT } from "next-auth/jwt"

// Auth.js v5 defaults to JWE (encrypted tokens), but the Lambda API decodes
// with python-jose using HS256. Override encode/decode to use plain HS256 JWT
// so both sides use the same NEXTAUTH_SECRET with the same algorithm.
function secretBytes() {
  return new TextEncoder().encode(process.env.NEXTAUTH_SECRET ?? "")
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
    }),
  ],
  callbacks: {
    jwt({ token, account }) {
      if (account?.providerAccountId) {
        token.sub = account.providerAccountId
      }
      return token
    },
    session({ session, token }) {
      if (token.sub) {
        session.user.id = token.sub
      }
      return session
    },
  },
  jwt: {
    encode: async ({ token }) => {
      return new SignJWT(token as Record<string, unknown>)
        .setProtectedHeader({ alg: "HS256" })
        .sign(secretBytes())
    },
    decode: async ({ token }) => {
      if (!token) return null
      const { payload } = await jwtVerify(token, secretBytes(), {
        algorithms: ["HS256"],
      })
      return payload as JWT
    },
  },
  pages: {
    signIn: "/auth/signin",
  },
})
