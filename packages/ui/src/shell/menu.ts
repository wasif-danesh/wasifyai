// What the side menu offers, in order (docs/desktop-profile.md, "The side menu's final shape"). The menu is
// defined once, here, and each app says what its items open: the desktop window opens its own screens, the web
// app opens its pages. An item an app does not serve yet is shown marked "Soon", never hidden, so both menus keep
// the same shape.
import {
  BookOpen,
  Box,
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
  { id: "models", label: "Models", icon: SquareStack },
  { id: "train", label: "Train models", icon: FlaskConical },
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
