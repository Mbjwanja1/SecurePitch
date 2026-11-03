import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "node", // Node 22 provides the same WebCrypto API as browsers
    include: ["tests/**/*.test.ts"],
  },
});
