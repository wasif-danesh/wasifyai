// Builds one of the pages of packages/ui/bundle (the new chat on its own, as a production build) into `outDir`. Shared by the bundle
// check (scripts/chat/check-bundle.mjs) and the Playwright check of the desktop window's content-security policy
// (apps/web/e2e/chat-csp.spec.ts). It uses the vite that apps/desktop builds with.
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const need = createRequire(join(root, "apps/desktop/package.json"));

export async function buildHarness(outDir, page = "index.html") {
  const { build } = await import(pathToFileURL(need.resolve("vite")).href);
  const react = (await import(pathToFileURL(need.resolve("@vitejs/plugin-react")).href)).default;
  const dir = join(root, "packages/ui/bundle");
  await build({
    root: dir,
    configFile: false,
    logLevel: "error",
    plugins: [react()],
    build: {
      outDir,
      emptyOutDir: true,
      target: "es2022",
      manifest: true,
      reportCompressedSize: false,
      rollupOptions: { input: join(dir, page) },
    },
  });
}
