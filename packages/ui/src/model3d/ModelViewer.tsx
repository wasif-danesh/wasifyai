"use client";

import { createElement, useEffect, useState } from "react";
import { cn } from "../cn";
import { loadViewer } from "./viewer-loader";

/**
 * A model in a viewer you can turn and zoom. `src` is an object URL of the GLB. It starts on the
 * front: the engine's front faces -Z, so the camera begins at 180 degrees (TD0). `loading="eager"`
 * because a viewer in a hidden pane never loads the model otherwise (TD0).
 */
export function ModelViewer({
  src,
  label,
  className,
}: {
  src: string;
  label: string;
  className?: string;
}) {
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let gone = false;
    loadViewer()
      .then(() => !gone && setReady(true))
      .catch(() => !gone && setFailed(true));
    return () => {
      gone = true;
    };
  }, []);
  if (failed) {
    return (
      <p role="alert" className="text-muted-foreground">
        The 3D viewer could not be loaded. You can still save the model as a file.
      </p>
    );
  }
  if (!ready) return <output className="text-muted-foreground">Opening the viewer…</output>;
  return (
    <div className={cn("overflow-hidden rounded-xl border bg-muted", className)}>
      {createElement("model-viewer", {
        src,
        alt: label,
        loading: "eager",
        "camera-controls": true,
        "touch-action": "pan-y",
        "camera-orbit": "180deg 80deg auto",
        "shadow-intensity": "0.8",
        "interaction-prompt": "none",
        style: { width: "100%", height: "min(62vh, 560px)", background: "transparent" },
      })}
    </div>
  );
}
