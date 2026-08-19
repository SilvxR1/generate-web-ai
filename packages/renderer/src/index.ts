// Entry point for the page composition renderer. Turns typed configuration
// from @generate-web-ai/site-config into rendered @generate-web-ai/blocks
// components — the layer between "data describing a site" and Astro output.
export { default as PageRenderer } from "./PageRenderer.astro";
export { default as BlockRenderer } from "./BlockRenderer.astro";
