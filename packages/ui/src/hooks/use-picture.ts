"use client";

import { HttpError, type RunClient } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { fileProblem } from "../pictures";

/** What a picture field needs from the app's client. */
export type PictureApi = Pick<RunClient, "uploadImage" | "deleteUpload">;

export type Picture = {
  uploadId: string;
  key: string; // what a run passes as `image_key`
  width: number;
  height: number;
  previewUrl: string; // made from the local file: no round trip
  name: string;
};

type Status = "idle" | "uploading" | "error";

/**
 * One picture for a form (ADR-0039): checks the file, uploads it at once, keeps its preview, and takes it
 * back from the server when the user removes or replaces it. Call `handOver()` when a run starts: the
 * run owns the picture from then on and will delete it itself.
 */
export function usePicture(product: string, api: PictureApi) {
  const { uploadImage, deleteUpload } = api;
  const [picture, setPicture] = useState<Picture | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const current = useRef<Picture | null>(null);
  const abort = useRef<AbortController | null>(null);
  const handedOver = useRef(false);

  const forget = useCallback(
    (p: Picture | null, remote: boolean) => {
      if (!p) return;
      URL.revokeObjectURL(p.previewUrl);
      if (remote) void deleteUpload(product, p.uploadId);
    },
    [product, deleteUpload],
  );

  const clear = useCallback(() => {
    abort.current?.abort();
    forget(current.current, true);
    current.current = null;
    setPicture(null);
    setStatus("idle");
    setError(null);
  }, [forget]);

  const choose = useCallback(
    async (file: File) => {
      const problem = fileProblem(file);
      if (problem) {
        setError(problem);
        setStatus("error");
        return;
      }
      abort.current?.abort(); // a second picture replaces the first, even while it uploads
      const ctrl = new AbortController();
      abort.current = ctrl;
      const old = current.current;
      setError(null);
      setStatus("uploading");
      const previewUrl = URL.createObjectURL(file);
      try {
        const up = await uploadImage(product, file, ctrl.signal);
        if (ctrl.signal.aborted) {
          URL.revokeObjectURL(previewUrl);
          void deleteUpload(product, up.upload_id);
          return;
        }
        forget(old, true);
        const next: Picture = {
          uploadId: up.upload_id,
          key: up.key,
          width: up.width,
          height: up.height,
          previewUrl,
          name: file.name,
        };
        current.current = next;
        setPicture(next);
        setStatus("idle");
      } catch (e) {
        URL.revokeObjectURL(previewUrl);
        if (ctrl.signal.aborted) return;
        setError(
          e instanceof HttpError
            ? e.message
            : "We couldn't upload that picture. Check your connection and try again.",
        );
        setStatus("error");
      }
    },
    [product, forget, uploadImage, deleteUpload],
  );

  const cancel = useCallback(() => {
    abort.current?.abort();
    setStatus("idle");
    setError(null);
  }, []);

  const handOver = useCallback(() => {
    handedOver.current = true;
    if (current.current) URL.revokeObjectURL(current.current.previewUrl);
    current.current = null;
  }, []);

  // Leaving the form with a picture that was never used: take it back from the server.
  useEffect(
    () => () => {
      abort.current?.abort();
      if (!handedOver.current) forget(current.current, true);
    },
    [forget],
  );

  return { picture, status, error, choose, clear, cancel, handOver };
}
