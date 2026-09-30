import { site } from "../../content/site";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <p className="site-footer__name">{site.name}</p>
      <p className="site-footer__city">{site.city}</p>
    </footer>
  );
}
