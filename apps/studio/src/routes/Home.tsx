import { Link } from "react-router-dom";

export function Home() {
  return (
    <section>
      <h1>AI Business Automation Studio</h1>
      <p>
        Turn a short business briefing into a ready-to-review website and lead-automation workflow — you approve
        every step before anything goes live.
      </p>
      <p>
        <Link to="/businesses/new">Start a new business →</Link>
      </p>
    </section>
  );
}
