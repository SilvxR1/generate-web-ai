#!/usr/bin/env node
// Headless equivalent of what Studio's PreviewStep.tsx does in the
// browser: read a persisted BusinessConfig (e.g. the `config` field
// from `GET /businesses/{id}`) and run it through the real
// generateSiteConfig() to get the SiteConfig `POST
// /businesses/{id}/website/publish` expects. Exists so scripts/CI/E2E
// runs can produce a real, non-fixture SiteConfig without driving a
// browser — the computation is identical to Studio's, not a
// reimplementation of it.
//
// Usage: node scripts/generate-from-business-config.ts < business-config.json > site-config.json
import { generateSiteConfig } from "../src/generateSiteConfig.ts";

const chunks: Buffer[] = [];
for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
const businessConfig = JSON.parse(Buffer.concat(chunks).toString("utf-8"));

process.stdout.write(JSON.stringify(generateSiteConfig(businessConfig)));
