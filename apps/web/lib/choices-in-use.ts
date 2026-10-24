// The "Select ... model" button for the groups an admin sets up for the whole service (ADR-0086 on the web): chat,
// images, video and 3D. The panel only shows what the service uses and whether it is ready: a person cannot choose
// or get a model here (the admin does, in Admin > Models and the media setup).
import type { InUseModel, Model3dApi, ModelsInUseApi } from "@wasifyai/client";
import type { ChoiceList, ChoicesApi, GroupId, ModelChoice } from "@wasifyai/ui";

export type InUseDeps = { inUse: ModelsInUseApi; model3d: Model3dApi };

const ASK_AN_ADMIN = "Not set up on this service yet. Ask an admin to add it.";

export const IN_USE_GROUPS: GroupId[] = ["chat", "images", "video", "three_d"];

export function inUseRow(m: InUseModel, chosen: boolean): ModelChoice {
  return {
    id: m.id,
    title: m.title,
    plain: m.plain,
    tier: "recommended",
    state: m.ready ? "ready" : "unavailable",
    chosen: chosen && m.ready,
    downloadBytes: 0,
    engineBytes: 0,
    engineName: null,
    fit: null,
    fitReason: null,
    licence: m.licence,
    commercial: m.licence ? "yes" : "unreviewed",
    licenceUrl: null,
    source: "app",
    unavailableReason: m.ready ? null : ASK_AN_ADMIN,
  };
}

export function inUseChoices(deps: InUseDeps, group: GroupId): ChoicesApi {
  return {
    async list(): Promise<ChoiceList> {
      if (group === "three_d") {
        const c = await deps.model3d.component();
        const row = inUseRow(
          {
            id: "pixal3d",
            title: "Pixal3D",
            plain: "Turns one picture into a 3D model you can turn around and save. Experimental.",
            ready: c.installed,
            licence: c.about.licence,
          },
          true,
        );
        return { choices: [row], diskFreeBytes: null, memoryBytes: null };
      }
      const all = await deps.inUse.inUse();
      const key = group === "chat" ? "chat" : group === "images" ? "images" : "video";
      const models = all[key];
      const first = models.findIndex((m) => m.ready);
      return {
        choices: models.map((m, i) => inUseRow(m, i === first)),
        diskFreeBytes: null,
        memoryBytes: null,
      };
    },
    async choose() {}, // the service uses one model for everyone; an admin changes it
    async get() {
      throw new Error(ASK_AN_ADMIN);
    },
  };
}
