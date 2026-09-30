import { createFileRoute } from "@tanstack/react-router";

import { Contact } from "../features/landing/Contact";
import { Hero } from "../features/landing/Hero";
import { SiteFooter } from "../features/landing/SiteFooter";
import { SiteHeader } from "../features/landing/SiteHeader";
import { Treatments } from "../features/landing/Treatments";

export const Route = createFileRoute("/")({
  component: Home,
});

function Home() {
  return (
    <>
      <SiteHeader />
      <main>
        <Hero />
        <Treatments />
        <Contact />
      </main>
      <SiteFooter />
    </>
  );
}
