import type { CategorizedError } from "./errors";

export function ErrorBanner({ error }: { error: CategorizedError }) {
  return (
    <div className="banner banner--error" role="alert">
      <p className="banner__title">{error.title}</p>
      <p>{error.message}</p>
      {error.technicalDetail && (
        <details className="banner__detail">
          <summary>Technical detail</summary>
          <code>{error.technicalDetail}</code>
        </details>
      )}
    </div>
  );
}
