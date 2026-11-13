// SPDX-License-Identifier: AGPL-3.0-only
// What runs on this window's engine, for the tray and the home's Running now (ADR-0093 U2, U9).
import { type TrayJob, jobLabel } from "@wasifyai/ui";
import { connectionsApi } from "./api";
import { videos } from "./videos";

export /**
 * The running jobs of this window's engine, for the tray: what each is doing, and Stop where it can be. A clip
 * made on the Video screen is a run, not an action, so the clips being made are listed too, by their words.
 */
async function runningJobs(): Promise<TrayJob[]> {
  const [{ jobs }, clips] = await Promise.all([
    connectionsApi.jobs(),
    videos
      .list({ limit: 5, status: "working" })
      .then((p) => p.videos)
      .catch(() => []),
  ]);
  // a clip an agent asked for is already listed as its action
  const asAction = jobs.some((j) => j.action_id.startsWith("video."));
  const making: TrayJob[] = asAction
    ? []
    : clips.map((v) => ({ id: v.id, label: `Making your video: ${v.prompt}` }));
  return [
    ...making,
    ...jobs.map((j) => ({
      id: j.job_id,
      label: jobLabel(j.action_id),
      from: j.from,
      seconds: j.seconds,
      onStop: j.cancellable
        ? async () => {
            await connectionsApi.cancelJob(j.job_id);
          }
        : undefined,
    })),
  ];
}
