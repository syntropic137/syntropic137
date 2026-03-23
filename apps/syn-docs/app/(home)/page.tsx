'use client';

import { HeroSection, FeaturesGrid, QuickLinksGrid } from './sections';

export default function HomePage() {
  return (
    <main className="flex-1">
      <HeroSection />
      <FeaturesGrid />
      <QuickLinksGrid />
    </main>
  );
}
