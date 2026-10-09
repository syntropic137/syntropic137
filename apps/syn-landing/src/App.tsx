import Nav from "./components/Nav";
import Hero from "./sections/Hero";
import WhatIs from "./sections/WhatIs";
import WhySyntropic from "./components/WhySyntropic";
import HowItWorks from "./components/HowItWorks";
import AgentControlPlane from "./components/AgentControlPlane";
import GitHubTriggers from "./components/GitHubTriggers";
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
        <hr className="section-divider" />
        <WhySyntropic />
        <hr className="section-divider" />
        <HowItWorks />
        <hr className="section-divider" />
        <AgentControlPlane />
        <hr className="section-divider" />
        <Observability />
        <hr className="section-divider" />
        <GitHubTriggers />
        <hr className="section-divider" />
        <Security />
        <hr className="section-divider" />
        <GetStarted />
      </main>
      <Footer />
    </>
  );
}
