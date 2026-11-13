// The products shown on the home page: one entry per card. Adding a product to the app is one
// entry here plus its own area under /<id>. `soon` cards show a "Coming soon" tag and link to a
// plain "Coming soon" page until the product is built (each has an ADR that designs it). Music, speech and lip
// sync are screens of the voice product (`/voice/<screen>`), which are always there.
export type Product = {
  id: "music" | "image" | "video" | "text-to-speech" | "speech-to-text" | "lip-sync";
  title: string;
  blurb: string;
  action: string; // the button on the card: what you do there
  href: string;
  status: "live" | "soon";
  /** The product's own views in the side panel (ADR-0046); the first is where the product starts. */
  views: { label: string; href: string }[];
  /** The kind it makes in My creations, used for the "My creations" link in its views. */
  library?: "songs" | "images" | "videos" | "speeches" | "transcripts" | "lipsyncs";
};

export const PRODUCTS: Product[] = [
  {
    id: "music",
    title: "Music",
    blurb: "Turn a story or feeling into lyrics, then hear it come to life.",
    action: "Create a song",
    href: "/voice/music",
    status: "live",
    views: [
      { label: "Create", href: "/voice/music" },
      { label: "In My creations", href: "/creations?show=songs" },
    ],
    library: "songs",
  },
  {
    id: "image",
    title: "Image",
    blurb: "Describe a scene or transform a picture into something new.",
    action: "Make an image",
    href: "/image",
    status: "live",
    views: [
      { label: "Create", href: "/image" },
      { label: "In My creations", href: "/creations?show=images" },
    ],
    library: "images",
  },
  {
    id: "video",
    title: "Video",
    blurb:
      "Describe a scene, or bring a picture to life as a short clip. Leave while it's made: we'll tell you when it's ready.",
    action: "Create a video",
    href: "/video",
    status: "live",
    views: [
      { label: "Create", href: "/video" },
      { label: "In My creations", href: "/creations?show=videos" },
    ],
    library: "videos",
  },
  {
    id: "text-to-speech",
    title: "Text to Speech",
    blurb:
      "Type or paste text, pick a language and a male or female voice, and get natural speech to play and download.",
    action: "Create speech",
    href: "/voice/speak",
    status: "live",
    views: [
      { label: "Create", href: "/voice/speak" },
      { label: "In My creations", href: "/creations?show=speeches" },
    ],
    library: "speeches",
  },
  {
    id: "speech-to-text",
    title: "Speech to Text",
    blurb:
      "Upload an audio or video file, or record your voice, and get a transcript with timestamps. Leave while it's made: we'll tell you when it's ready.",
    action: "Transcribe audio",
    href: "/voice/transcribe",
    status: "live",
    views: [
      { label: "Create", href: "/voice/transcribe" },
      { label: "In My creations", href: "/creations?show=transcripts" },
    ],
    library: "transcripts",
  },
  {
    id: "lip-sync",
    title: "Lip Sync",
    blurb:
      "Give a character image a voice, a song or a script, and watch it speak or sing in sync.",
    action: "Create lip sync",
    href: "/voice/lipsync",
    status: "live",
    views: [
      { label: "Create", href: "/voice/lipsync" },
      { label: "In My creations", href: "/creations?show=lipsyncs" },
    ],
    library: "lipsyncs",
  },
];

/** The products to show: all of them (the voice product is always on). */
export function currentProducts(): Product[] {
  return PRODUCTS;
}
