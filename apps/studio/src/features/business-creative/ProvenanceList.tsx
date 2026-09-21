import type { ProvenanceRow } from "./creativeProvenance";

// Read-only provenance for one creative direction. Swatches are drawn only from
// the pre-validated #RRGGBB values provenanceRows() produces — this component
// never turns arbitrary backend text into a style.
export function ProvenanceList({ rows }: { rows: ProvenanceRow[] }) {
  return (
    <ul className="generative-workflow-panel__provenance">
      {rows.map((row) => (
        <li key={row.label} className="field-hint">
          {row.label}: {row.value}
          {row.swatches?.map((color) => (
            <span
              key={color}
              className="site-preview__swatch"
              style={{ background: color, marginLeft: "0.35rem" }}
              title={color}
              data-testid="brand-palette-swatch"
            />
          ))}
        </li>
      ))}
    </ul>
  );
}
