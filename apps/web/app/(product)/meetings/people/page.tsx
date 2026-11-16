import { PeopleScreen } from "@/components/meetings/MeetingsScreen";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "People" };

export default function Page() {
  return <PeopleScreen />;
}
