import type { CreationEntry, CreationsNav, MakeScreen } from "@wasifyai/ui";

const MAKE: Record<MakeScreen, string> = {
  music: "/voice/music",
  image: "/image",
  video: "/video",
  speech: "/voice/speak",
  transcribe: "/voice/transcribe",
  lipsync: "/voice/lipsync",
};

/** Where an entry of My creations opens on the web: its own page where it has one, else the shared screen that holds the history. */
export function hrefOf(target: CreationEntry | MakeScreen): string {
  if (typeof target === "string") return MAKE[target];
  switch (target.kind) {
    case "song":
      return "/voice/tracks";
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
  }
}

/** The navigation My creations needs: real links, handled by the app's own router. */
export function webCreationsNav(push: (href: string) => void): CreationsNav {
  return { href: hrefOf, open: (entry) => push(hrefOf(entry)), make: (to) => push(hrefOf(to)) };
}
