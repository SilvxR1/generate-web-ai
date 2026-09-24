/**
 * Header navigation (A8.3.3), derived from the page's FINAL block list:
 * one link per navigable section that actually renders, in rendered order,
 * labelled with that section's own heading (the fixed preset copy the page
 * already shows). No section is added for navigation's sake, the hero and
 * the CTA are never listed, and contact, which always renders last, is
 * the final link.
 *
 * Invariant: every generated href is "#<id>" of a block on the page, so
 * PlatformContract's broken_anchor_target check can never fire for it.
 */
import type { BlockConfig, SiteNavigationItem } from "@generate-web-ai/site-config";

const NAVIGABLE_SECTION_IDS = new Set(["about", "gallery", "services", "contact"]);

export function buildNavigation(blocks: readonly BlockConfig[]): SiteNavigationItem[] {
  const navigation: SiteNavigationItem[] = [];
  for (const block of blocks) {
    if (!block.id || !NAVIGABLE_SECTION_IDS.has(block.id)) continue;
    const heading = (block.content as { heading?: unknown }).heading;
    if (typeof heading !== "string" || heading.trim().length === 0) continue;
    navigation.push({ label: heading.trim(), href: `#${block.id}` });
  }
  return navigation;
}
