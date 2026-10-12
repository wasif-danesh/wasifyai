import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./tailwind.css";

export const metadata: Metadata = {
  title: { default: "WasifyAI Studio", template: "%s · WasifyAI Studio" },
  description: "Turn your ideas into music, images and video.",
};

export const viewport: Viewport = {
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f3ef" },
    { media: "(prefers-color-scheme: dark)", color: "#111214" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh bg-background font-sans text-step-0 leading-[1.55] text-foreground antialiased selection:bg-primary/35">
        <a
          className="fixed top-3 left-3 z-[100] -translate-y-[200%] rounded-md bg-surface px-4 py-2 text-foreground focus:translate-y-0"
          href="#main"
        >
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
