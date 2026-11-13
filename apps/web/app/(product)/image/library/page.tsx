import { redirect } from "next/navigation";

/** "Your images" is the Library now, showing pictures (ADR-0093, U8). */
export default function ImageLibraryPage() {
  redirect("/creations?show=images");
}
