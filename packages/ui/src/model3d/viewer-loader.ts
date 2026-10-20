// Loads Google's <model-viewer> (Apache-2.0, ADR-0080 decision 7) the first time a model is shown, so
// the screens that never show a model do not carry it. A seam for the tests: jsdom has no WebGL.
let loading: Promise<unknown> | null = null;

export function loadViewer(): Promise<unknown> {
  loading ??= import("@google/model-viewer");
  return loading;
}
