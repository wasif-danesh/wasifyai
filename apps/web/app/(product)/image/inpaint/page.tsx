import { ImageScreen } from "@/components/image/ImageScreens";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Inpaint a picture" };

export default function Page() {
  return <ImageScreen mode="inpaint" />;
}
