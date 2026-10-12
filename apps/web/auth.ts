// Sign-in with Auth.js (ADR-0030): a JWT session cookie, no database. A provider is offered only
// when its client id and secret are set. The API never sees this cookie: the BFF turns the
// session into a short-lived API token (lib/api-token.ts).
import { verifiedPrimaryEmail } from "@/lib/github-email";
import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";
import Google from "next-auth/providers/google";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";

declare module "next-auth" {
  interface Session {
    wasifyai?: { provider: string; accountId: string; emailVerified: boolean };
  }
}
const has = (...names: string[]) => names.every((n) => Boolean(process.env[n]));

/** The providers that are set up, as `{ id, name }` for the sign-in page. */
export function configuredProviders(): { id: string; name: string }[] {
  const out: { id: string; name: string }[] = [];
  if (has("AUTH_GOOGLE_ID", "AUTH_GOOGLE_SECRET")) out.push({ id: "google", name: "Google" });
  if (has("AUTH_GITHUB_ID", "AUTH_GITHUB_SECRET")) out.push({ id: "github", name: "GitHub" });
  if (
    has(
      "AUTH_MICROSOFT_ENTRA_ID_ID",
      "AUTH_MICROSOFT_ENTRA_ID_SECRET",
      "AUTH_MICROSOFT_ENTRA_ID_ISSUER",
    )
  )
    out.push({ id: "microsoft-entra-id", name: "Microsoft" });
  return out;
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    ...(has("AUTH_GOOGLE_ID", "AUTH_GOOGLE_SECRET") ? [Google] : []),
    ...(has("AUTH_GITHUB_ID", "AUTH_GITHUB_SECRET") ? [GitHub] : []),
    ...(has(
      "AUTH_MICROSOFT_ENTRA_ID_ID",
      "AUTH_MICROSOFT_ENTRA_ID_SECRET",
      "AUTH_MICROSOFT_ENTRA_ID_ISSUER",
    )
      ? [MicrosoftEntraID]
      : []),
  ],
  pages: { signIn: "/signin" },
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account) {
        token.provider = account.provider;
        token.accountId = account.providerAccountId;
        // Google vouches for the address itself; GitHub only on request (its primary, verified
        // address). Microsoft never counts, so it never links accounts by email.
        token.emailVerified = account.provider === "google" && profile?.email_verified === true;
        if (account.provider === "github") {
          const email = await verifiedPrimaryEmail(account.access_token);
          if (email) {
            token.email = email;
            token.emailVerified = true;
          }
        }
      }
      return token;
    },
    session({ session, token }) {
      if (typeof token.provider === "string" && typeof token.accountId === "string") {
        session.wasifyai = {
          provider: token.provider,
          accountId: token.accountId,
          emailVerified: token.emailVerified === true,
        };
      }
      return session;
    },
  },
});
