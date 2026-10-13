import Nav from "./components/Nav";
import Hero from "./sections/Hero";
import WhatIs from "./sections/WhatIs";
import Workflows from "./sections/Workflows";
import Harnesses from "./sections/Harnesses";
import Observability from "./sections/Observability";
import Evals from "./sections/Evals";
import UseCases from "./sections/UseCases";
import WhyPlatform from "./sections/WhyPlatform";
import Start from "./sections/Start";
import Footer from "./components/Footer";

export default function App() {
  return (
    <>
      <a href="#main-content" className="skip-link">Skip to content</a>
      <Nav />
      <main id="main-content">
        <Hero />
        <WhatIs />
        <Workflows />
        <Harnesses />
        <Observability />
        <Evals />
        <UseCases />
        <WhyPlatform />
        <Start />
      </main>
      <Footer />
    </>
  );
}
