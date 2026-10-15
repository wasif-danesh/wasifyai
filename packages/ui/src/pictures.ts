// Picking, dropping and pasting a picture (ADR-0039). Pure helpers: no React, no network.
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp"];

/** Why a chosen file cannot be used, or null. The server checks again; this saves a wasted upload. */
export function fileProblem(file: File): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) return "Please choose a PNG, JPEG or WebP picture.";
  if (file.size > MAX_UPLOAD_BYTES)
    return "That picture is over 10 MB. Please choose a smaller one.";
  if (file.size === 0) return "That file is empty.";
  return null;
}

type Transfer = Pick<DataTransfer, "items" | "files"> | null | undefined;

/** The first picture file in a drag or clipboard transfer, or null. Text and links are ignored, so a
 * text paste into the prompt box is left alone. A file of another kind (a PDF) is returned as is so the
 * caller can say why it was refused; only a transfer with no file at all gives null. */
export function firstFile(transfer: Transfer): File | null {
  if (!transfer) return null;
  const items = Array.from(transfer.items ?? []);
  for (const item of items) {
    if (item.kind === "file") {
      const file = item.getAsFile();
      if (file) return named(file);
    }
  }
  const file = transfer.files?.[0];
  return file ? named(file) : null;
}

/** True when a drag carries files (not just text or a link): the form highlights only then. */
export function hasFiles(transfer: Pick<DataTransfer, "types"> | null | undefined): boolean {
  return Array.from(transfer?.types ?? []).includes("Files");
}

/** Some browsers hand a pasted screenshot over without a name. */
function named(file: File): File {
  if (file.name) return file;
  const ext = file.type === "image/jpeg" ? "jpg" : file.type === "image/webp" ? "webp" : "png";
  return new File([file], `pasted-picture.${ext}`, { type: file.type });
}
