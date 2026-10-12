// The short-lived token the BFF sends to the API (ADR-0030). The API verifies it with the same
// shared secret; the browser's session cookie never leaves this server.
import { SignJWT } from "jose";
import { authEnabled } from "./auth-mode";

const MIN_SECRET_BYTES = 32;
const LIFETIME_SECONDS = 300;

export type ApiTokenClaims = {
  provider: string;
  accountId: string;
  email?: string | null;
  emailVerified: boolean;
  name?: string | null;
  image?: string | null;
};

export async function mintApiToken(
  claims: ApiTokenClaims,
  secret: string | undefined = process.env.API_AUTH_SECRET,
): Promise<string> {
  if (!secret || new TextEncoder().encode(secret).length < MIN_SECRET_BYTES) {
    throw new Error("API_AUTH_SECRET is missing or shorter than 32 bytes");
  }
  return new SignJWT({
    email: claims.email ?? undefined,
    email_verified: claims.emailVerified,
    name: claims.name ?? undefined,
    picture: claims.image ?? undefined,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(`${claims.provider}:${claims.accountId}`)
    .setIssuer("wasifyai-web")
    .setAudience("wasifyai-api")
    .setIssuedAt()
    .setExpirationTime(`${LIFETIME_SECONDS}s`)
    .sign(new TextEncoder().encode(secret));
}

/**
 * Headers that identify the signed-in user to the API: `{}` when sign-in is off (stub mode) and
 * `null` when sign-in is on but nobody is signed in.
 */
export async function apiAuthHeaders(): Promise<Record<string, string> | null> {
  if (!authEnabled()) return {};
  const { auth } = await import("@/auth");
  const session = await auth();
  if (!session?.wasifyai) return null;
  const token = await mintApiToken({
    provider: session.wasifyai.provider,
    accountId: session.wasifyai.accountId,
    email: session.user?.email,
    emailVerified: session.wasifyai.emailVerified,
    name: session.user?.name,
    image: session.user?.image,
  });
  return { authorization: `Bearer ${token}` };
}
