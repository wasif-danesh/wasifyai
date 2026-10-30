import { StylesAdmin } from "@/components/admin/StylesAdmin";
import { muted } from "@/lib/styles";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Styles" };
export const dynamic = "force-dynamic";

export default function Styles() {
  return (
    <>
      <p className={muted}>
        Styles (also called LoRAs) change the look of a picture. The ones added here are for
        everyone on this service: people choose them on the image screens and set how strongly they
        apply; they cannot add or delete them. Each file is fetched from Hugging Face at the version
        you look at, checked, and kept in the service's storage.
      </p>
      <StylesAdmin />
    </>
  );
}
