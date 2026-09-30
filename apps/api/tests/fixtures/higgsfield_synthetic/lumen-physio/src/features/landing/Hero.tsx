import { site } from "../../content/site";

export function Hero() {
  return (
    <section className="hero">
      <img alt="Physiotherapist working with a patient" className="hero__image" src="/media/hero-clinic.jpg" />
      <div className="hero__copy">
        <p className="hero__eyebrow">{site.hero.eyebrow}</p>
        <h1 className="hero__title">{site.hero.title}</h1>
        <p className="hero__lead">{site.hero.lead}</p>
      </div>
    </section>
  );
}
