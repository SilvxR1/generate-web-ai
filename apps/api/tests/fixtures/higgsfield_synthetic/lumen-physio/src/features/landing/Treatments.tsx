import { site } from "../../content/site";

export function Treatments() {
  return (
    <section className="treatments" id="treatments">
      <h2 className="section-title">Treatments</h2>
      <ul className="treatments__grid">
        {site.treatments.map((treatment) => (
          <li className="treatment" key={treatment.title}>
            <h3>{treatment.title}</h3>
            <p>{treatment.text}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
