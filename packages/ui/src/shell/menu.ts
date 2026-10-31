// What the side menu offers, in order. The menu is defined once, here, and each app says what its items open:
// the desktop window opens its own screens, the web app opens its pages. An item an app does not serve yet is
// shown marked "Soon", never hidden, so both menus keep the same shape.
//
// `MENU_GROUPS` and `EXTRA_ITEMS` are the items: one per screen, the ids the actions' `ui` pointers and the web's
// parity rows name (docs/contracts/actions.json, apps/web/lib/parity.ts). The menu shows the groups, one open at
// a time (the owner kept this over a flat menu with tabs in the bar, 2026-10-28).
import {
  BookOpen,
  Box,
  Clapperboard,
  FilePlus2,
  FileText,
  Film,
  FlaskConical,
  Headphones,
  Image as ImageIcon,
  Languages,
  Library,
  type LucideIcon,
  Maximize2,
  Mic,
  Music,
  Paintbrush,
  Pencil,
  Scissors,
  Shapes,
  Shuffle,
  Sparkles,
  SquarePen,
  SquareStack,
  Users,
  Video,
  Volume2,
} from "lucide-react";

export type MenuItemDef = { id: string; label: string; icon: LucideIcon };
export type MenuGroupDef = { id: string; label: string; icon: LucideIcon; items: MenuItemDef[] };

export const MENU_GROUPS: MenuGroupDef[] = [
  {
    id: "notebook",
    label: "Notebook",
    icon: BookOpen,
    items: [
      { id: "notebook.create", label: "Create", icon: FilePlus2 },
      { id: "notebook.list", label: "View notebooks", icon: BookOpen },
    ],
  },
  {
    id: "images",
    label: "Images",
    icon: ImageIcon,
    items: [
      { id: "images.create", label: "Create", icon: Sparkles },
      { id: "images.edit", label: "Edit", icon: Pencil },
      { id: "images.inpaint", label: "Inpaint", icon: Paintbrush },
      { id: "images.reference", label: "Reference", icon: SquareStack },
    ],
  },
  {
    id: "video",
    label: "Video",
    icon: Video,
    items: [
      { id: "video.create", label: "Create", icon: Sparkles },
      { id: "video.animate", label: "Animate an image", icon: Film },
      { id: "video.extend", label: "Extend video", icon: Maximize2 },
    ],
  },
  {
    id: "voice",
    label: "Voice",
    icon: Volume2,
    items: [
      { id: "voice.speak", label: "Text to speech", icon: Volume2 },
      { id: "voice.transcribe", label: "Speech to text", icon: Mic },
      { id: "voice.lipsync", label: "Lip sync", icon: Film },
      { id: "voice.voices", label: "Voices", icon: Users },
      { id: "voice.convert", label: "Change a voice", icon: Shuffle },
      { id: "voice.edit", label: "Edit speech", icon: Pencil },
      { id: "voice.dub", label: "Dub a recording", icon: Languages },
      { id: "voice.audiobook", label: "Audiobook", icon: Headphones },
    ],
  },
  {
    id: "music",
    label: "Music",
    icon: Music,
    items: [
      { id: "music.create", label: "Create", icon: Sparkles },
      { id: "music.lyrics", label: "Lyrics", icon: FileText },
      { id: "music.separate", label: "Split into parts", icon: Scissors },
    ],
  },
];

/** The single items above and below the groups. */
export const CHAT_ITEM: MenuItemDef = { id: "chat", label: "New chat", icon: SquarePen };
export const EXTRA_ITEMS: MenuItemDef[] = [
  { id: "creative", label: "Creative Studio", icon: Clapperboard },
  { id: "motion", label: "Motion graphics", icon: Shapes },
  { id: "model3d", label: "3D model", icon: Box },
  { id: "library", label: "Library", icon: Library },
  { id: "train", label: "Train models", icon: FlaskConical },
  { id: "models", label: "Model hub", icon: SquareStack },
];

/** What an app says about one item. No answer means the app does not serve it yet: it shows as "Soon". */
export type ItemView =
  | { hidden: true }
  | {
      /** where it goes on a web page; an app without addresses leaves it out */
      href?: string;
      /** what choosing it does when it is not just following `href` */
      onSelect?: () => void;
      /** whether it is the page being shown */
      current?: boolean;
    };

export type ItemResolver = (id: string) => ItemView | undefined;

/** The group an item belongs to, if it is in one. */
export function groupOf(itemId: string): MenuGroupDef | undefined {
  return MENU_GROUPS.find((g) => g.items.some((i) => i.id === itemId));
}

/** What the top bar calls the screen a person is on: its group's name, or the item's own; null when none is current. */
export function titleOf(resolve: ItemResolver): string | null {
  const current = (item: MenuItemDef) => {
    const v = resolve(item.id);
    return v !== undefined && !("hidden" in v) && v.current === true;
  };
  for (const group of MENU_GROUPS) if (group.items.some(current)) return group.label;
  if (current(CHAT_ITEM)) return "Chat";
  const extra = EXTRA_ITEMS.find(current);
  return extra ? extra.label : null;
}

/** Every tool an app serves, with its words ("Images: Edit"), for the search box. */
export function placesOf(
  resolve: ItemResolver,
): { id: string; label: string; view: Exclude<ItemView, { hidden: true }> }[] {
  const out: { id: string; label: string; view: Exclude<ItemView, { hidden: true }> }[] = [];
  const add = (item: MenuItemDef, label: string) => {
    const v = resolve(item.id);
    if (v !== undefined && !("hidden" in v)) out.push({ id: item.id, label, view: v });
  };
  add(CHAT_ITEM, "Chat");
  for (const group of MENU_GROUPS)
    for (const item of group.items) add(item, `${group.label}: ${item.label}`);
  for (const item of EXTRA_ITEMS) add(item, item.label);
  return out;
}
