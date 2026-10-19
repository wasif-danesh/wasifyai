import { auth, signOut } from "@/auth";
import { Button } from "@/components/ui/button";
import { authEnabled } from "@/lib/auth-mode";
import { getMe } from "@/lib/me";
import Link from "next/link";
import { connection } from "next/server";
import { Logo } from "./Logo";
import { NavLink } from "./NavLink";
import { ThemeToggle } from "./ThemeToggle";
import { Activity } from "./shell/Activity";

export async function Header() {
  await connection(); // per request: the session is not known at build time
  const session = authEnabled() ? await auth() : null;
  const signedIn = !authEnabled() || Boolean(session);
  const isAdmin = signedIn && (await getMe())?.role === "admin";
  const who = session?.user?.name ?? session?.user?.email;
  return (
    <header className="sticky top-0 z-20 border-b bg-background">
      <div className="mx-auto flex min-h-15 w-[min(100%-2rem,70rem)] flex-wrap items-center justify-between gap-x-3 gap-y-1.5 py-2 sm:w-[min(100%-3rem,70rem)] md:gap-x-4 md:py-1.5">
        <Logo />
        <nav
          className="order-3 flex w-full min-w-0 gap-1 overflow-x-auto whitespace-nowrap [scrollbar-width:none] md:order-none md:w-auto [&::-webkit-scrollbar]:hidden"
          aria-label="Main"
        >
          <NavLink href="/music" exact>
            Music
          </NavLink>
          <NavLink href="/image" exact>
            Image
          </NavLink>
          <NavLink href="/video" exact>
            Video
          </NavLink>
          {signedIn && <NavLink href="/creations">My creations</NavLink>}
          {isAdmin && <NavLink href="/admin">Admin</NavLink>}
        </nav>
        <div className="ms-auto flex items-center justify-end gap-3 max-[420px]:gap-2">
          <Activity enabled={signedIn} />
          <ThemeToggle />
          {who ? (
            <form
              className="flex items-center gap-2.5"
              action={async () => {
                "use server";
                await signOut({ redirectTo: "/signin" });
              }}
            >
              <span
                className="hidden max-w-[12ch] truncate text-ui text-muted-foreground md:inline"
                title={session?.user?.email ?? undefined}
              >
                {who}
              </span>
              <Button type="submit" variant="outline" size="sm">
                Sign out
              </Button>
            </form>
          ) : !signedIn ? (
            <Button asChild size="sm">
              <Link href="/signin">Sign in</Link>
            </Button>
          ) : null}
        </div>
      </div>
    </header>
  );
}
