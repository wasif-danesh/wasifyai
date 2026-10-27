"use client";

import { webTraining } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import { Train } from "@wasifyai/ui";
import { useRouter } from "next/navigation";

/** Train models: the shared screen (also the desktop's), talking to the BFF. The teaching is done on the service's worker. */
export function TrainScreen() {
  const router = useRouter();
  return (
    <Train
      api={webTraining}
      place="service"
      runs={webClient}
      onOpenLibrary={() => router.push("/creations")}
    />
  );
}
