import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import type { z } from "zod";

const SYN_DIR = process.env.SYN_CONFIG_DIR || path.join(os.homedir(), ".syntropic137");

export function synPath(...segments: string[]): string {
  return path.join(SYN_DIR, ...segments);
}

export function readJsonFile<T>(
  filePath: string,
  schema: z.ZodType<unknown, z.ZodTypeDef, unknown>,
  fallback: T,
): T {
  if (!fs.existsSync(filePath)) return fallback;
  try {
    const content = fs.readFileSync(filePath, "utf-8");
    return schema.parse(JSON.parse(content)) as T;
  } catch {
    return fallback;
  }
}

export function writeJsonFile(filePath: string, data: unknown): void {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2) + "\n", "utf-8");
}
