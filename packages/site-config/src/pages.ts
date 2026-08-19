import type { BlockConfig } from "./blocks.ts";

export interface PageConfig {
  path: string;
  blocks: BlockConfig[];
}
