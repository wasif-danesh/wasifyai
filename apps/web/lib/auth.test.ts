import { jwtVerify } from "jose";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiAuthHeaders, mintApiToken } from "./api-token";
import { authEnabled, isPublicPath, safeNext, signInReason } from "./auth-mode";

const SECRET = "s".repeat(40);
const key = new TextEncoder().encode(SECRET);

afterEach(() => {
  process.env.AUTH_MODE = "stub";
  vi.doUnmock("@/auth");
  vi.resetModules();
});

describe("mintApiToken", () => {
  const claims = {
    provider: "google",
    accountId: "1001",
    email: "ann@example.com",
    emailVerified: true,
    name: "Ann",
  };

  it("signs a short-lived token the API can verify", async () => {
    const token = await mintApiToken(claims, SECRET);
    const { payload } = await jwtVerify(token, key, {
      issuer: "wasifyai-web",
      audience: "wasifyai-api",
    });
    expect(payload.sub).toBe("google:1001");
    expect(payload.email).toBe("ann@example.com");
    expect(payload.email_verified).toBe(true);
    expect((payload.exp ?? 0) - (payload.iat ?? 0)).toBe(300);
  });

  it("is not verifiable with another secret", async () => {
    const token = await mintApiToken(claims, SECRET);
    await expect(jwtVerify(token, new TextEncoder().encode("x".repeat(40)))).rejects.toThrow();
  });

  it.each([undefined, "", "too-short"])("refuses the secret %j", async (secret) => {
    await expect(mintApiToken(claims, secret)).rejects.toThrow(/API_AUTH_SECRET/);
  });
});

describe("apiAuthHeaders", () => {
  it("sends nothing in stub mode", async () => {
    expect(await apiAuthHeaders()).toEqual({});
  });

  it("is null when sign-in is on and nobody is signed in", async () => {
    process.env.AUTH_MODE = "jwt";
    vi.doMock("@/auth", () => ({ auth: async () => null }));
    expect(await apiAuthHeaders()).toBeNull();
  });

  it("sends a bearer token for the signed-in user", async () => {
    process.env.AUTH_MODE = "jwt";
    process.env.API_AUTH_SECRET = SECRET;
    vi.doMock("@/auth", () => ({
      auth: async () => ({
        user: { email: "ann@example.com", name: "Ann" },
        wasifyai: { provider: "github", accountId: "77", emailVerified: false },
      }),
    }));
    const headers = await apiAuthHeaders();
    const token = headers?.authorization?.replace("Bearer ", "") ?? "";
    const { payload } = await jwtVerify(token, key, {
      issuer: "wasifyai-web",
      audience: "wasifyai-api",
    });
    expect(payload.sub).toBe("github:77");
    expect(payload.email_verified).toBe(false);
  });
});

describe("auth mode and redirects", () => {
  it("is on unless AUTH_MODE=stub", () => {
    Reflect.deleteProperty(process.env, "AUTH_MODE");
    expect(authEnabled()).toBe(true);
    process.env.AUTH_MODE = "stub";
    expect(authEnabled()).toBe(false);
  });

  it.each([
    ["/songs", "/songs"],
    ["/songs/1?x=1", "/songs/1?x=1"],
    ["//evil.example", "/"],
    ["https://evil.example", "/"],
    ["/\\evil.example", "/"],
    ["", "/"],
    [undefined, "/"],
  ])("sends %j to %j after sign-in", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });
});

describe("which pages need a session", () => {
  it.each(["/", "/signin"])("%s is public", (path) => {
    expect(isPublicPath(path)).toBe(true);
  });

  it.each([
    "/music",
    "/music/songs",
    "/music/songs/1",
    "/songs",
    "/admin",
    "/admin/models",
    "/somewhere-else",
    "/image",
    "/image/",
    "/image/creations",
    "/image/secret",
    "/video",
    "/text-to-speech",
    "/speech-to-text",
    "/speech-to-text/creations/1",
    "/video/",
    "/video/creations/1",
    "/signin/x",
  ])("%s needs a session", (path) => {
    expect(isPublicPath(path)).toBe(false);
  });

  it("explains the sign-in in terms of where the visitor was going", () => {
    expect(signInReason("/music")).toMatch(/create music/);
    expect(signInReason("/music/songs/abc")).toMatch(/create music/);
    expect(signInReason("/image")).toMatch(/create images/);
    expect(signInReason("/image/creations/x")).toMatch(/create images/);
    expect(signInReason("/video")).toMatch(/create videos/);
    expect(signInReason("/video/creations/x")).toMatch(/create videos/);
    expect(signInReason("/text-to-speech")).toMatch(/create speech/);
    expect(signInReason("/speech-to-text/creations/x")).toMatch(/transcribe/);
    expect(signInReason("/admin")).toBe("Sign in to continue.");
    expect(signInReason("/")).toBe("Sign in to continue.");
  });
});
