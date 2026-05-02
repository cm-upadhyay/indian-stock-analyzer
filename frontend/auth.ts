import NextAuth from "next-auth"
import Google from "next-auth/providers/google"

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
    }),
  ],
  callbacks: {
    jwt({ token, account }) {
      // Persist the Google sub as token.sub on first sign-in
      if (account?.providerAccountId) {
        token.sub = account.providerAccountId
      }
      return token
    },
    session({ session, token }) {
      // Expose user.id (= Google sub) to server-side session reads
      if (token.sub) {
        session.user.id = token.sub
      }
      return session
    },
  },
  pages: {
    signIn: "/auth/signin",
  },
})
