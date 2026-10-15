"use client";

import { Button } from "@/components/ui/button";
import { webClient } from "@/lib/run-client";
import { CreateImage as SharedCreateImage } from "@wasifyai/ui";
import Link from "next/link";

/** The image screen of the web app: the shared screen, talking to the BFF, with a download link and a
 * link to My creations next to the result. */
export function CreateImage() {
  return (
    <SharedCreateImage
      client={webClient}
      resultActions={(result) => ({
        primary: result.imageId ? (
          <Button asChild>
            <a href={`/api/products/wasifyai-image/images/${result.imageId}/download`} download>
              Download
            </a>
          </Button>
        ) : null,
        more: result.imageId ? (
          <Button asChild variant="outline">
            <Link href={`/image/creations/${result.imageId}`}>Open in My creations</Link>
          </Button>
        ) : null,
      })}
    />
  );
}
