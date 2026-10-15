// SPDX-License-Identifier: AGPL-3.0-only
import type { ImageSummary } from "@wasifyai/client";
import { ImageLibrary, presetOf } from "@wasifyai/ui";
import { images } from "../images";
import type { Route } from "../router";

/** Everything made on this computer: the shared library screen, with "make it again" going to Create. */
export function LibraryPage({
  go,
  onRunAgain,
}: {
  go: (r: Route) => void;
  onRunAgain: (image: ImageSummary) => void;
}) {
  return (
    <ImageLibrary
      images={images}
      canSave
      onCreate={() => go("create")}
      onRunAgain={(image) => presetOf(image) && onRunAgain(image)}
    />
  );
}
