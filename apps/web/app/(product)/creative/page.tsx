import { CreativeScreen } from "@/components/creative/CreativeScreen";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Creative Studio" };

/** `?open=<id>` opens one project, as the Library's card does. */
export default async function Page({ searchParams }: { searchParams: Promise<{ open?: string }> }) {
  return <CreativeScreen open={(await searchParams).open ?? null} />;
}
