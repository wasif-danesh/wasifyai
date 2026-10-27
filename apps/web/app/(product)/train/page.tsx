import { TrainScreen } from "@/components/train/TrainScreen";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Train models" };

export default function Page() {
  return <TrainScreen />;
}
