import { SearchAdmin } from "@/components/admin/SearchAdmin";
import { muted } from "@/lib/styles";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Search" };
export const dynamic = "force-dynamic";

export default function Search() {
  return (
    <>
      <p className={muted}>
        The web search of the chat box, as the desktop's Settings has it. Your choice here is for
        everyone, the key is kept encrypted and never shown again, and each person still has to
        allow searching for themself.
      </p>
      <SearchAdmin />
    </>
  );
}
