import { HeadContent, Outlet, Scripts, createRootRoute } from "@tanstack/react-router";
import type { ReactNode } from "react";

import appMeta from "../app-meta.json";
import siteCss from "../styles/site.css?url";

const TITLE = appMeta.og_title ?? "Lumen Physio — Physiotherapy in Lisbon";
const DESCRIPTION = appMeta.og_description ?? "Physiotherapy in Lisbon.";

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: TITLE },
      { name: "description", content: DESCRIPTION },
      { name: "robots", content: "index, follow" },
      { property: "og:title", content: TITLE },
      { property: "og:description", content: DESCRIPTION },
      { property: "og:site_name", content: "Lumen Physio" },
      ...(appMeta.og_image_url ? [{ property: "og:image", content: appMeta.og_image_url }] : []),
    ],
    links: [
      { rel: "preconnect", href: "https://fonts.googleapis.com" },
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Fraunces:wght@600&family=Inter:wght@400;500&display=swap",
      },
      { rel: "stylesheet", href: siteCss },
      { rel: "icon", href: appMeta.favicon_url ?? "/favicon.svg", type: "image/svg+xml" },
    ],
  }),
  shellComponent: Shell,
  component: () => <Outlet />,
});

function Shell({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}
