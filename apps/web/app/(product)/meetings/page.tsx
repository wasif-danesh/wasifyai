import { MeetingsScreen } from "@/components/meetings/MeetingsScreen";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Meetings" };

/** `?open=<id>` opens one meeting, as the Library's card and search do. */
export default async function Page({ searchParams }: { searchParams: Promise<{ open?: string }> }) {
  return <MeetingsScreen open={(await searchParams).open ?? null} />;
}
