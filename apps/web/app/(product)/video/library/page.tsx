import { redirect } from "next/navigation";

/** "Your videos" is the Library now, showing videos (ADR-0093, U8). */
export default function VideoLibraryPage() {
  redirect("/creations?show=videos");
}
