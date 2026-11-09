import { readFileSync } from "node:fs";

const manifest = JSON.parse(readFileSync(new URL("../.next/server/app-paths-manifest.json", import.meta.url), "utf8"));
for (const route of ["/__internal/oauth/delete/route", "/__internal/oauth/drop/route"]) {
  if (!(route in manifest)) {
    throw new Error(`OAuth internal route is missing from the production build: ${route}`);
  }
}
