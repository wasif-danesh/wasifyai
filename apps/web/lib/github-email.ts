// GitHub reports whether an address is verified only on /user/emails (ADR-0025, ADR-0030). Only a
// primary, verified address counts; any failure means "not verified".
type Fetch = typeof fetch;

export async function verifiedPrimaryEmail(
  accessToken: string | undefined,
  fetchImpl: Fetch = fetch,
): Promise<string | null> {
  if (!accessToken) return null;
  try {
    const res = await fetchImpl("https://api.github.com/user/emails", {
      headers: {
        authorization: `Bearer ${accessToken}`,
        accept: "application/vnd.github+json",
        "user-agent": "wasifyai",
      },
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    const emails: unknown = await res.json();
    if (!Array.isArray(emails)) return null;
    for (const e of emails) {
      if (e?.primary === true && e?.verified === true && typeof e?.email === "string") {
        return e.email;
      }
    }
  } catch {
    // network error or bad JSON: treat as unverified
  }
  return null;
}
