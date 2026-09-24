// A8.2.2 — resolveDesignFamily is the canonical family resolution; apps/api
// mirrors it in app.creative.internal_direction to derive a
// WebsiteCreativeDirection's "current" family. Both are held to this one
// fixture so they can never disagree about which family a business is in.
import type { BusinessVertical } from "@generate-web-ai/business-config-types";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { resolveDesignFamily } from "./design.ts";

interface FamilyCase {
  industry: BusinessVertical;
  visualStyle: string | null;
  realGalleryAssetCount: number;
  family: string;
}

const { cases } = JSON.parse(
  readFileSync(new URL("../fixtures/design-family.conformance.json", import.meta.url), "utf-8"),
) as { cases: FamilyCase[] };

describe("resolveDesignFamily — shared design-family conformance", () => {
  it.each(cases)("$industry / $visualStyle / $realGalleryAssetCount photos -> $family", (c) => {
    expect(resolveDesignFamily(c.industry, c.visualStyle, c.realGalleryAssetCount)).toBe(c.family);
  });
});
