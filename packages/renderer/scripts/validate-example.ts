// Standalone, framework-free validation: proves (1) every block in the
// example SiteConfig — which covers all current block types — passes
// the renderer's type check, and (2) an unrecognized block type fails
// clearly instead of being silently ignored. Run with:
//   node scripts/validate-example.ts
import { assertKnownBlockType, BLOCK_TYPES, exampleSiteConfig, type BlockConfig } from "@generate-web-ai/site-config";

let failures = 0;

function check(description: string, fn: () => void): void {
  try {
    fn();
    console.log(`PASS: ${description}`);
  } catch (error) {
    failures += 1;
    console.error(`FAIL: ${description}`);
    console.error(`  ${(error as Error).message}`);
  }
}

const page = exampleSiteConfig.pages[0];
if (!page) {
  throw new Error("exampleSiteConfig has no pages to validate.");
}

const blockTypesInExample = new Set(page.blocks.map((block) => block.type));
const expectedTypes = BLOCK_TYPES;

check(`example SiteConfig covers all ${expectedTypes.length} known block types`, () => {
  for (const type of expectedTypes) {
    if (!blockTypesInExample.has(type as BlockConfig["type"])) {
      throw new Error(`example is missing a "${type}" block`);
    }
  }
});

check("every block in the example SiteConfig is a known, renderable type", () => {
  for (const block of page.blocks) {
    assertKnownBlockType(block);
  }
});

check("a block with an unrecognized type fails clearly instead of being ignored", () => {
  const bogusBlock = { type: "pricing", content: {} } as unknown as BlockConfig;
  let threw = false;
  try {
    assertKnownBlockType(bogusBlock);
  } catch (error) {
    threw = true;
    const message = (error as Error).message;
    if (!message.includes("pricing")) {
      throw new Error(`error message did not name the offending type: ${message}`);
    }
  }
  if (!threw) {
    throw new Error("assertKnownBlockType did not throw for an unknown block type");
  }
});

if (failures > 0) {
  console.error(`\n${failures} check(s) failed.`);
  process.exit(1);
}

console.log("\nAll checks passed.");
