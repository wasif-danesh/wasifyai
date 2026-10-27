// What the side menu offers, in order. The menu is defined once, here, and each app says what its items open:
// the desktop window opens its own screens, the web app opens its pages. An item an app does not serve yet is
// shown marked "Soon", never hidden, so both menus keep the same shape.
//
// `MENU_GROUPS` and `EXTRA_ITEMS` are the items: one per screen, the ids the actions' `ui` pointers and the web's
// parity rows name (docs/contracts/actions.json, apps/web/lib/parity.ts). `MENU_ENTRIES` is what the menu shows
// since stage U2 of the UI plan (ADR-0093): eleven entries, no groups to open, a tool one click away; an entry
// with several items shows them as tabs in the top bar.
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
      { id: "images.library", label: "Your images", icon: Library },
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
      { id: "video.library", label: "Your videos", icon: Library },
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
      { id: "music.library", label: "Your music", icon: Library },
      { id: "music.lyrics", label: "Lyrics", icon: FileText },
      { id: "music.separate", label: "Split into parts", icon: Scissors },
    ],
  },
];

/** The single items above and below the groups. */
export const CHAT_ITEM: MenuItemDef = { id: "chat", label: "New chat", icon: SquarePen };
export const EXTRA_ITEMS: MenuItemDef[] = [
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

/** One entry of the side menu: what it is called, and the items it stands for (the first is where it opens). */
export type MenuEntryDef = {
  id: string;
  label: string;
  icon: LucideIcon;
  /** the screens under this entry; more than one and they are the tabs of the top bar */
  items: MenuItemDef[];
};

const items = (groupId: string, ...ids: string[]): MenuItemDef[] => {
  const group = MENU_GROUPS.find((g) => g.id === groupId);
  return ids.map((id) => {
    const item = group?.items.find((i) => i.id === id);
    if (!item) throw new Error(`no menu item ${id}`);
    return item;
  });
};
const extra = (id: string): MenuItemDef => {
  const item = EXTRA_ITEMS.find((i) => i.id === id);
  if (!item) throw new Error(`no menu item ${id}`);
  return item;
};

/** The side menu since stage U2: eleven entries, each one click, with a product's modes as tabs in the bar. */
export const MENU_ENTRIES: MenuEntryDef[] = [
  { id: "chat", label: "Chat", icon: SquarePen, items: [CHAT_ITEM] },
  {
    id: "notebooks",
    label: "Notebooks",
    icon: BookOpen,
    items: items("notebook", "notebook.list"),
  },
  {
    id: "images",
    label: "Images",
    icon: ImageIcon,
    items: items(
      "images",
      "images.create",
      "images.edit",
      "images.inpaint",
      "images.reference",
      "images.library",
    ),
  },
  {
    id: "video",
    label: "Video",
    icon: Video,
    items: items("video", "video.create", "video.animate", "video.extend", "video.library"),
  },
  { id: "motion", label: "Motion graphics", icon: Shapes, items: [extra("motion")] },
  {
    id: "speech",
    label: "Speech",
    icon: Volume2,
    items: items(
      "voice",
      "voice.speak",
      "voice.transcribe",
      "voice.voices",
      "voice.convert",
      "voice.edit",
    ),
  },
  {
    id: "studio",
    label: "Studio",
    icon: Clapperboard,
    items: items("voice", "voice.dub", "voice.audiobook", "voice.lipsync"),
  },
  {
    id: "music",
    label: "Music",
    icon: Music,
    items: items("music", "music.create", "music.lyrics", "music.separate", "music.library"),
  },
  { id: "model3d", label: "3D model", icon: Box, items: [extra("model3d")] },
  { id: "library", label: "Library", icon: Library, items: [extra("library")] },
  { id: "train", label: "Train models", icon: FlaskConical, items: [extra("train")] },
  { id: "models", label: "Model hub", icon: SquareStack, items: [extra("models")] },
];

/** The entry an item belongs to (an item outside the entries, such as `notebook.create`, has none). */
export function entryOf(itemId: string): MenuEntryDef | undefined {
  return MENU_ENTRIES.find((e) => e.items.some((i) => i.id === itemId));
}

/** What the top bar shows for the entry a person is in: its title and, with more than one item, its tabs. */
export type BarPlace = {
  entry: MenuEntryDef;
  /** the item that is current, if one is */
  item: MenuItemDef | null;
  tabs: { item: MenuItemDef; view: Exclude<ItemView, { hidden: true }> }[];
};

/** Where a person is, from what the app says is current; null when no entry's item is current (Settings). */
export function placeOf(resolve: ItemResolver): BarPlace | null {
  for (const entry of MENU_ENTRIES) {
    const views = entry.items.map((item) => ({ item, view: resolve(item.id) }));
    const current = views.find((v) => v.view && !("hidden" in v.view) && v.view.current);
    if (!current) continue;
    const tabs = views.flatMap((v) =>
      v.view && !("hidden" in v.view) ? [{ item: v.item, view: v.view }] : [],
    );
    return { entry, item: current.item, tabs: tabs.length > 1 ? tabs : [] };
  }
  return null;
}
