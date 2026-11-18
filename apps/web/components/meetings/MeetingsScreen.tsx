"use client";

import { webMeetings } from "@/lib/library";
import { Meetings, People } from "@wasifyai/ui";
import { useRouter } from "next/navigation";

/** Meetings on the web (ADR-0108 decision 7): from a file only, written down with speakers by the
 * cloud model an admin chose; questions go to the person's notebooks. */
export function MeetingsScreen({ open }: { open: string | null }) {
  const router = useRouter();
  return (
    <Meetings
      api={webMeetings}
      hosted
      initialId={open}
      onOpenNotebook={(id) => router.push(`/notebooks/${encodeURIComponent(id)}`)}
    />
  );
}

/** The people named in the person's meetings. */
export function PeopleScreen() {
  const router = useRouter();
  return <People api={webMeetings} hosted onOpenMeetings={() => router.push("/meetings")} />;
}
