// Verifies the stdin/stdout wiring of generate-from-business-config.ts
// against the same generateSiteConfig() call made directly — the CLI
// must be a pure pass-through, never a second implementation.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { exampleReformaValenciaConfig } from "@generate-web-ai/business-config-types";
import { describe, expect, it } from "vitest";
import { generateSiteConfig } from "../src/generateSiteConfig.ts";

const scriptPath = fileURLToPath(new URL("./generate-from-business-config.ts", import.meta.url));

describe("generate-from-business-config CLI", () => {
  it("prints the exact SiteConfig generateSiteConfig() would produce for the given BusinessConfig", () => {
    const stdout = execFileSync("node", [scriptPath], {
      input: JSON.stringify(exampleReformaValenciaConfig),
      encoding: "utf-8",
    });

    expect(JSON.parse(stdout)).toEqual(generateSiteConfig(exampleReformaValenciaConfig));
  });
});
