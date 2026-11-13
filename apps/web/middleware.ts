// Page requests need a session when sign-in is on (ADR-0030), except the public ones (home and the
// "coming soon" pages). API requests (/api) are left to the
// BFF route handlers, which answer 401 instead of redirecting, so fetches get JSON.
import { auth } from "@/auth";
import { authEnabled, isPublicPath } from "@/lib/auth-mode";
import { type NextFetchEvent, type NextRequest, NextResponse } from "next/server";

const guard = auth((req) => {
  if (req.auth || isPublicPath(req.nextUrl.pathname)) return NextResponse.next();
  const url = new URL("/signin", req.nextUrl.origin);
  url.searchParams.set("next", req.nextUrl.pathname + req.nextUrl.search);
  return NextResponse.redirect(url);
});

/** The addresses of the older music, speech and lip sync pages, now screens of the voice product. */
const MOVED: Record<string, string> = {
  "/music": "/voice/music",
  "/text-to-speech": "/voice/speak",
  "/speech-to-text": "/voice/transcribe",
  "/lip-sync": "/voice/lipsync",
};

export default function middleware(req: NextRequest, event: NextFetchEvent) {
  const to = MOVED[req.nextUrl.pathname];
  if (to) return NextResponse.redirect(new URL(to, req.nextUrl.origin));
  if (!authEnabled()) return NextResponse.next();
  return (guard as unknown as (r: NextRequest, e: NextFetchEvent) => Promise<Response>)(req, event);
}

export const config = { matcher: ["/((?!api|_next/static|_next/image|favicon.ico|signin).*)"] };
