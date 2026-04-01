'use client';

import { HeroSection, FeaturesGrid, QuickLinksGrid, SocialFooter } from './sections';

export default function HomePage() {
  return (
    <main className="flex-1">
      <HeroSection />
      <FeaturesGrid />
      <QuickLinksGrid />
      <SocialFooter />
    </main>
  );
}
