import { CreationsScreen } from "@/components/creations/CreationsScreen";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Library" };
export const dynamic = "force-dynamic";

export default async function Creations({
  searchParams,
}: {
  searchParams: Promise<{ show?: string; open?: string }>;
}) {
  const { show, open } = await searchParams;
  return <CreationsScreen show={show} open={open} />;
}
