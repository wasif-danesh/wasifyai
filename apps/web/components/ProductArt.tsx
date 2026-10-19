import type { Product } from "@/lib/products";

/** Simple vector art in the theme's colours, one per product. Decorative: hidden from screen readers. */
export function ProductArt({ id }: { id: Product["id"] }) {
  return (
    <svg
      className="aspect-[16/10] w-full rounded-control bg-muted"
      viewBox="0 0 320 190"
      aria-hidden="true"
      focusable="false"
    >
      {ART[id]}
    </svg>
  );
}

const ART: Record<Product["id"], React.ReactNode> = {
  music: <MusicArt />,
  image: <ImageArt />,
  video: <VideoArt />,
  "text-to-speech": <SpeechArt />,
  "speech-to-text": <TranscribeArt />,
  "lip-sync": <LipSyncArt />,
};

function MusicArt() {
  const heights = [22, 38, 58, 82, 54, 102, 70, 96, 48, 80, 58, 36, 22];
  return (
    <g>
      <defs>
        <radialGradient id="music-art-bg" cx="52%" cy="42%" r="75%">
          <stop offset="0" stopColor="#6747ce" />
          <stop offset="0.48" stopColor="#30245f" />
          <stop offset="1" stopColor="#171528" />
        </radialGradient>
        <linearGradient id="music-art-bars" x1="0" x2="0" y1="0" y2="1">
          <stop stopColor="#d1fb83" />
          <stop offset="1" stopColor="#a99bff" />
        </linearGradient>
      </defs>
      <rect width="320" height="190" fill="url(#music-art-bg)" />
      <circle
        fill="none"
        stroke="white"
        strokeOpacity="0.13"
        strokeWidth="1"
        cx="160"
        cy="88"
        r="63"
      />
      <circle
        fill="none"
        stroke="white"
        strokeOpacity="0.13"
        strokeWidth="1"
        cx="160"
        cy="88"
        r="89"
      />
      {heights.map((h, i) => (
        <rect
          // biome-ignore lint/suspicious/noArrayIndexKey: a fixed decorative list
          key={i}
          x={82 + i * 12}
          y={88 - h / 2}
          width="5"
          height={h}
          rx="2.5"
          fill="url(#music-art-bars)"
        />
      ))}
    </g>
  );
}

function ImageArt() {
  return (
    <g>
      <defs>
        <linearGradient id="image-art-bg" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#f1bd85" />
          <stop offset="0.5" stopColor="#d88179" />
          <stop offset="1" stopColor="#4a457c" />
        </linearGradient>
        <linearGradient id="image-art-back" x1="0" y1="0" x2="0" y2="1">
          <stop stopColor="#976d8d" />
          <stop offset="1" stopColor="#49406f" />
        </linearGradient>
        <linearGradient id="image-art-front" x1="0" y1="0" x2="0" y2="1">
          <stop stopColor="#48416e" />
          <stop offset="1" stopColor="#252846" />
        </linearGradient>
      </defs>
      <rect width="320" height="190" fill="url(#image-art-bg)" />
      <circle cx="241" cy="51" r="24" fill="#ffdc9e" />
      <circle cx="241" cy="51" r="38" fill="#ffdc9e" opacity="0.18" />
      <path d="M0 190 52 100l45 44 78-91 68 79 33-39 44 50v47Z" fill="url(#image-art-back)" />
      <path d="m0 190 70-72 43 38 73-64 70 58 35-31 29 31v40Z" fill="url(#image-art-front)" />
      <path d="M0 166q49-20 102 5t112-2 106 3v18H0Z" fill="#de9b79" opacity="0.35" />
    </g>
  );
}

function VideoArt() {
  return (
    <g>
      <defs>
        <linearGradient id="video-art-bg" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#142a36" />
          <stop offset="0.55" stopColor="#287078" />
          <stop offset="1" stopColor="#c68a59" />
        </linearGradient>
        <radialGradient id="video-art-orb" cx="32%" cy="26%" r="80%">
          <stop stopColor="#f7d8aa" />
          <stop offset="0.48" stopColor="#d58a68" />
          <stop offset="1" stopColor="#68415e" />
        </radialGradient>
      </defs>
      <rect width="320" height="190" fill="url(#video-art-bg)" />
      <circle cx="170" cy="80" r="88" fill="url(#video-art-orb)" />
      <path d="M0 133q78-41 144-4t176-3v64H0Z" fill="#10232f" opacity="0.68" />
      <circle
        cx="160"
        cy="95"
        r="27"
        fill="#ffffff"
        fillOpacity="0.22"
        stroke="#ffffff"
        strokeOpacity="0.5"
      />
      <path d="m155 83 18 12-18 12Z" fill="#fff" />
    </g>
  );
}

/** Text to speech: lines of text turning into a speaker's sound waves. */
function SpeechArt() {
  return (
    <g>
      <defs>
        <linearGradient id="tts-art-bg" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#1d2b4f" />
          <stop offset="0.6" stopColor="#4a4fa3" />
          <stop offset="1" stopColor="#c76f8f" />
        </linearGradient>
      </defs>
      <rect width="320" height="190" fill="url(#tts-art-bg)" />
      {[64, 84, 104, 124].map((y, i) => (
        <rect
          key={y}
          x="38"
          y={y}
          width={[92, 112, 78, 98][i]}
          height="8"
          rx="4"
          fill="#fff"
          fillOpacity="0.55"
        />
      ))}
      <path d="M176 78h18l26-22v78l-26-22h-18Z" fill="#fff" fillOpacity="0.92" />
      <path
        d="M236 76q16 19 0 38M252 62q27 33 0 66M268 48q38 47 0 94"
        fill="none"
        stroke="#fff"
        strokeOpacity="0.7"
        strokeWidth="5"
        strokeLinecap="round"
      />
    </g>
  );
}

/** Speech to text: a microphone and the transcript it produces. */
function TranscribeArt() {
  return (
    <g>
      <defs>
        <linearGradient id="stt-art-bg" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#14343a" />
          <stop offset="0.55" stopColor="#1f7a6e" />
          <stop offset="1" stopColor="#d8b96a" />
        </linearGradient>
      </defs>
      <rect width="320" height="190" fill="url(#stt-art-bg)" />
      <rect x="58" y="42" width="44" height="72" rx="22" fill="#fff" fillOpacity="0.92" />
      <path
        d="M44 98q0 46 36 46t36-46M80 144v22M62 166h36"
        fill="none"
        stroke="#fff"
        strokeOpacity="0.8"
        strokeWidth="6"
        strokeLinecap="round"
      />
      {[52, 76, 100, 124].map((y, i) => (
        <g key={y}>
          <rect x="150" y={y} width="26" height="9" rx="4.5" fill="#fff" fillOpacity="0.4" />
          <rect
            x="184"
            y={y}
            width={[96, 82, 100, 60][i]}
            height="9"
            rx="4.5"
            fill="#fff"
            fillOpacity="0.8"
          />
        </g>
      ))}
    </g>
  );
}

/** Lip sync: a character whose mouth moves with a sound wave around it. */
function LipSyncArt() {
  return (
    <g>
      <defs>
        <linearGradient id="lip-art-bg" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#2a1a45" />
          <stop offset="0.55" stopColor="#8a3f7c" />
          <stop offset="1" stopColor="#f0a06a" />
        </linearGradient>
        <radialGradient id="lip-art-face" cx="40%" cy="32%" r="80%">
          <stop stopColor="#ffe3c2" />
          <stop offset="1" stopColor="#e8a47c" />
        </radialGradient>
      </defs>
      <rect width="320" height="190" fill="url(#lip-art-bg)" />
      {[0, 1, 2].map((i) => (
        <circle
          key={i}
          cx="160"
          cy="95"
          r={66 + i * 20}
          fill="none"
          stroke="#fff"
          strokeOpacity={0.35 - i * 0.1}
          strokeWidth="3"
          strokeDasharray="4 9"
        />
      ))}
      <circle cx="160" cy="95" r="52" fill="url(#lip-art-face)" />
      <circle cx="142" cy="84" r="5" fill="#3a2440" />
      <circle cx="178" cy="84" r="5" fill="#3a2440" />
      <ellipse cx="160" cy="116" rx="17" ry="11" fill="#7a2f4a" />
      <ellipse cx="160" cy="120" rx="10" ry="5" fill="#e87a8a" />
    </g>
  );
}
