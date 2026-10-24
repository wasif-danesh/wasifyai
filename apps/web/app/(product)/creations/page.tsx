import { CreationsScreen } from "@/components/creations/CreationsScreen";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "My creations" };
export const dynamic = "force-dynamic";

export default async function Creations({
  searchParams,
}: {
  searchParams: Promise<{ show?: string }>;
}) {
  const { show } = await searchParams;
  return <CreationsScreen show={show} />;
}
