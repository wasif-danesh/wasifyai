import { NotebookListScreen } from "@/components/notebook/NotebookScreens";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Notebooks" };

export default function NotebooksPage() {
  return <NotebookListScreen />;
}
