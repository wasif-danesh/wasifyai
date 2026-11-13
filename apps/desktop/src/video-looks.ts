// SPDX-License-Identifier: AGPL-3.0-only
// The looks the person taught the video model (Train models): read from the engine when the Video screen opens.
import { useVideoLooks as useLooks } from "@wasifyai/ui";
import { training } from "./training";

export const useVideoLooks = () => useLooks(training);
