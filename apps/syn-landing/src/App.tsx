import Nav from "./components/Nav";
import Hero from "./components/Hero";
import HowItWorks from "./components/HowItWorks";
import AgentControlPlane from "./components/AgentControlPlane";
import GitHubTriggers from "./components/GitHubTriggers";
import Observability from "./components/Observability";
import Security from "./components/Security";
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
        <Evals />
        <UseCases />
        <WhyPlatform />
        <Start />
      </main>
      <Footer />
    </>
  );
}
