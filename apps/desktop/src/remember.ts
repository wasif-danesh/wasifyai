// SPDX-License-Identifier: AGPL-3.0-only
// Small per-person conveniences kept in the webview (a model chosen last time). Never required: if
// storage is blocked the screen still works and just forgets.
export const remembered = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string): void {
    try {
      localStorage.setItem(key, value);
    } catch {
      // forgotten
    }
  },
};
