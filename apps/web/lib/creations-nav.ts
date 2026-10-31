import { AGAIN, EDIT } from "@/components/image/ImageScreens";
import { ANIMATE, EXTEND } from "@/components/video/VideoScreens";
import { putHandoff } from "@/lib/handoff";
import { remembered } from "@/lib/remembered";
import { presetOf } from "@wasifyai/ui";
import {
  type CreationEntry,
  type CreationUse,
  type CreationsNav,
  type MakeTarget,
  openInMusic,
  sendToTool,
} from "@wasifyai/ui";

const MAKE: Record<MakeTarget, string> = {
  music: "/voice/music",
  image: "/image",
  video: "/video",
  speech: "/voice/speak",
  transcribe: "/voice/transcribe",
  lipsync: "/voice/lipsync",
};

/** Where an entry of the Library opens "in its tool" on the web: its own page where it has one, else the tool. */
export function hrefOf(target: CreationEntry | MakeTarget): string {
  if (typeof target === "string") return MAKE[target];
  switch (target.kind) {
    case "song":
      return "/voice/music";
    case "image":
      return `/image/creations/${target.id}`;
    case "video":
      return `/video/creations/${target.id}`;
    case "speech":
      return "/voice/speak";
    case "transcript":
      return "/voice/transcribe";
    case "lipsync":
      return "/voice/lipsync";
    case "model3d":
      return "/image/3d";
    case "composition":
      return "/video/builder";
    case "creative_project": // desktop first (ADR-0090); the web shows it in the Library only
      return "/creations";
    case "notebook":
      return `/notebooks/${target.id}`;
    case "taught":
      return "/train";
  }
}

/** Which tool an entry can be handed to, and where that tool is. */
function useOf(entry: CreationEntry, action: CreationUse): string | null {
  switch (action) {
    case "edit":
      return entry.kind === "image" ? "/image/edit" : null;
    case "animate":
      return entry.kind === "image" ? "/video/animate" : null;
    case "extend":
      return entry.kind === "video" ? "/video/extend" : null;
    case "again":
      return entry.kind === "image" ? "/image" : entry.kind === "song" ? "/voice/music" : null;
    case "split":
      return entry.kind === "song" ? "/voice/separate" : null;
    case "convert":
      return entry.kind === "song" || entry.kind === "speech" ? "/voice/convert" : null;
    case "speechedit":
      return entry.kind === "song" || entry.kind === "speech" ? "/voice/edit" : null;
  }
}

/** The navigation the Library needs: real links, handled by the app's own router, and the hand-offs to the tools
 * (the same ones "Edit this" and "Animate this" use on the make screens). */
export function webCreationsNav(push: (href: string) => void): CreationsNav {
  return {
    href: hrefOf,
    open: (entry) => push(hrefOf(entry)),
    make: (to) => push(hrefOf(to)),
    canUse: (entry, action) => useOf(entry, action) !== null,
    use(entry, action) {
      const to = useOf(entry, action);
      if (!to) return;
      if (entry.kind === "image") {
        const image = entry.image;
        if (action === "edit")
          putHandoff(EDIT, { url: image.image_url, name: `${image.id}.png`, id: image.id });
        if (action === "animate")
          putHandoff(ANIMATE, { url: image.image_url, name: `${image.id}.png`, id: image.id });
        if (action === "again") {
          const preset = presetOf(image);
          if (preset) putHandoff(AGAIN, preset);
        }
      }
      if (entry.kind === "video" && action === "extend") putHandoff(EXTEND, entry.video);
      if (entry.kind === "song" && action === "again") openInMusic(remembered, "again", entry.id);
      if (action === "split" || action === "convert" || action === "speechedit") {
        sendToTool(remembered, {
          kind: entry.kind === "speech" ? "speech" : "track",
          id: entry.id,
        });
      }
      push(to);
    },
  };
}
