import fs from 'node:fs';
import path from 'node:path';

export function collectMdxFiles(dir: string): { filepath: string; content: string }[] {
  const results: { filepath: string; content: string }[] = [];

  function walk(d: string) {
    for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
      const full = path.join(d, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.mdx')) {
        results.push({ filepath: full, content: fs.readFileSync(full, 'utf-8') });
      }
    }
  }

  walk(dir);
  return results;
}
