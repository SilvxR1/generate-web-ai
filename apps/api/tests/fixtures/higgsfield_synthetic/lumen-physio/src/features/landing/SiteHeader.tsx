import { Link } from "@tanstack/react-router";

import { site } from "../../content/site";

export function SiteHeader() {
  return (
    <header className="site-header">
      <a className="site-header__brand" href="/">
        <img alt="" className="site-header__logo" height={28} src="/brand/lumen-logo.svg" width={28} />
        {site.name}
      </a>
      <nav className="site-header__nav">
        <a href="/#treatments">Treatments</a>
        <Link to="/studio">Studio</Link>
        <a className="site-header__cta" href="/#contact">
          Book an assessment
        </a>
      </nav>
    </header>
  );
}
