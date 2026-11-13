import { ImageScreen } from "@/components/image/ImageScreens";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Make a picture from references" };

export default function Page() {
  return <ImageScreen mode="reference" />;
}
