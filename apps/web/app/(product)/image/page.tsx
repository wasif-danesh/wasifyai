import { ImageScreen } from "@/components/image/ImageScreens";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Image" };

export default function ImagePage() {
  return <ImageScreen mode="text" />;
}
