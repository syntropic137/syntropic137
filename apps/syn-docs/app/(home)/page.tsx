'use client';

import { HeroContent, QuickLinksGrid, SocialFooter } from './sections';
import { HeroScene } from '@/components/HeroScene';

export default function HomePage() {
  return (
    <main className="flex-1">
      {/* Full-viewport hero with Three.js background */}
      <section className="relative min-h-[100dvh] flex flex-col overflow-hidden">
        {/* Three.js canvas — absolutely positioned behind everything */}
        <div className="absolute inset-0 z-0">
          <HeroScene />
        </div>

        {/* Content overlay */}
        <div className="relative z-10 flex flex-col justify-center flex-1 gap-6 pb-6">
          <HeroContent />
          <QuickLinksGrid />
        </div>
      </section>

      <SocialFooter />
    </main>
  );
}
