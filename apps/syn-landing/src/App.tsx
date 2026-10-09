import Nav from "./components/Nav";
import Hero from "./sections/Hero";
import WhatIs from "./sections/WhatIs";
import Workflows from "./sections/Workflows";
import Harnesses from "./sections/Harnesses";
import WhySyntropic from "./components/WhySyntropic";
import Observability from "./components/Observability";
import Security from "./components/Security";
import GetStarted from "./components/GetStarted";
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
        <hr className="section-divider" />
        <WhySyntropic />
        <hr className="section-divider" />
        <Observability />
        <hr className="section-divider" />
        <Security />
        <hr className="section-divider" />
        <GetStarted />
      </main>
      <Footer />
    </>
  );
}
