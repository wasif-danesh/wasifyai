import { ImageScreen } from "@/components/image/ImageScreens";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Edit a picture" };

export default function EditImagePage() {
  return <ImageScreen mode="image" />;
}
