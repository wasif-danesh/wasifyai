import { DesignPage } from "@/components/design/DesignPage";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Design" };

/** Every shared component in every state, in both themes: the page a stage of the UI plan is checked against. */
export default function Page() {
  return <DesignPage />;
}
