import { Model3dScreen } from "@/components/model3d/Model3dScreen";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "3D model" };

export default function Page() {
  return <Model3dScreen />;
}
