#!/usr/bin/env ts-node
/**
 * Generate AEF architecture diagram with configuration
 * 
 * Usage:
 *   ts-node scripts/generate-architecture-diagram.ts
 *   # or via justfile: just diagram
 */

import * as fs from 'fs';
import { ArchitectureSvgGenerator } from '../lib/event-sourcing-platform/vsa/vsa-visualizer/src/generators/architecture-svg-generator';
import { parseManifest } from '../lib/event-sourcing-platform/vsa/vsa-visualizer/src/manifest/parser';

const MANIFEST_PATH = '.topology/syn-manifest.json';
const OUTPUT_PATH = 'docs/architecture/vsa-overview.svg';

async function main() {
  console.log('🏗️  Generating AEF Architecture Diagram...\n');
  
  // Read manifest
  console.log(`📖 Reading manifest: ${MANIFEST_PATH}`);
  const manifestContent = fs.readFileSync(MANIFEST_PATH, 'utf-8');
  const manifest = parseManifest(manifestContent);
  
  // Configuration from vsa.yaml (matching the diagram section)
  const config = {
    applications: ['AEF CLI', 'Dashboard API', 'Dashboard UI'],
    infrastructure: [
      { name: 'TimescaleDB', description: 'Projections' },
      { name: 'EventStore', description: 'Events' },
      { name: 'Redis', description: 'Cache' },
      { name: 'MinIO', description: 'Artifacts' }
    ],
    packages: ['syn-domain', 'syn-adapters', 'syn-collector', 'syn-shared'],
    libraries: [
      { 
        name: 'agentic-primitives',
        repo: 'github.com/neuralempowerment/agentic-primitives'
      },
      { 
        name: 'event-sourcing-platform',
        repo: 'github.com/neuralempowerment/event-sourcing-platform'
      }
    ]
  };
  
  // Generate SVG
  console.log(`🎨 Generating SVG...`);
  const generator = new ArchitectureSvgGenerator(manifest, config);
  const svg = generator.generate();
  
  // Write to file
  fs.writeFileSync(OUTPUT_PATH, svg);
  const stats = fs.statSync(OUTPUT_PATH);
  const sizeKB = (stats.size / 1024).toFixed(2);
  
  console.log(`\n✅ Architecture diagram generated!`);
  console.log(`\n📊 Summary:`);
  console.log(`   Contexts:        ${manifest.bounded_contexts?.length || 0}`);
  console.log(`   Applications:    ${config.applications.length}`);
  console.log(`   Infrastructure:  ${config.infrastructure.length}`);
  console.log(`   Packages:        ${config.packages.length}`);
  console.log(`   Libraries:       ${config.libraries.length}`);
  console.log(`\n📝 Output:`);
  console.log(`   File: ${OUTPUT_PATH}`);
  console.log(`   Size: ${sizeKB} KB`);
  console.log(`\n💡 Embed in README.md:`);
  console.log(`   ![AEF Architecture](./docs/architecture/vsa-overview.svg)\n`);
}

main().catch(error => {
  console.error('❌ Error generating diagram:', error);
  process.exit(1);
});
