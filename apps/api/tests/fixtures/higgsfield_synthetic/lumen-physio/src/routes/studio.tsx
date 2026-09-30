import { createFileRoute } from "@tanstack/react-router";

import { SiteFooter } from "../features/landing/SiteFooter";
import { SiteHeader } from "../features/landing/SiteHeader";
import { site } from "../content/site";

export const Route = createFileRoute("/studio")({
  head: () => ({ meta: [{ title: site.studio.title }] }),
  component: Studio,
});

function Studio() {
  return (
    <>
      <SiteHeader />
      <main className="studio">
        <h1 className="studio__title">{site.studio.title}</h1>
        {site.studio.paragraphs.map((paragraph) => (
          <p className="studio__text" key={paragraph}>
            {paragraph}
          </p>
        ))}
        <div className="studio__gallery">
          <img alt="Treatment room with natural light" loading="lazy" src="/media/room-1.jpg" />
          <img alt="Exercise studio" loading="lazy" src="/media/room-2.jpg" />
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
