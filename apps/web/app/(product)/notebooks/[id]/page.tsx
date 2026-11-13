import { NotebookScreen } from "@/components/notebook/NotebookScreens";
import { NEW_NOTEBOOK } from "@/lib/notebook-ids";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

export const metadata: Metadata = { title: "Notebook" };
type Props = { params: Promise<{ id: string }> };

export default async function NotebookPage({ params }: Props) {
  const { id } = await params;
  // `new` is a draft; a saved notebook has a 32-character hexadecimal id
  if (id !== NEW_NOTEBOOK && !/^[0-9a-f]{32}$/.test(id)) notFound();
  return <NotebookScreen key={id} notebook={id} />;
}
