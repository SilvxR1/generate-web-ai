import { useState } from "react";
import { ApiError, NetworkError } from "../../lib/api";
import { login, type CurrentUser } from "../../lib/auth";

interface LoginScreenProps {
  /** Called once login succeeds — AppShell owns what happens next
   * (storing the user/tenants, showing the real app). This component
   * has no opinion on that beyond "here is who just logged in". */
  onLoggedIn: (user: CurrentUser) => void;
}

/** A2's one and only entry point into Studio — no signup, no password
 * reset, no "forgot password" here (see apps/api's app.routers.auth own
 * docstring: those are all explicitly deferred). An operator account is
 * created out of band; this screen only ever authenticates one. */
export function LoginScreen({ onLoggedIn }: LoginScreenProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const user = await login(email, password);
      onLoggedIn(user);
    } catch (cause) {
      if (cause instanceof ApiError) {
        // Deliberately the backend's own generic message here — it is
        // already written to never distinguish "wrong password" from
        // "no such account" (see login_with_password's own docstring on
        // the backend), and this screen must not undo that by adding
        // any more specific wording of its own.
        setError(cause.message);
      } else if (cause instanceof NetworkError) {
        setError("Could not reach the server. Check your connection and try again.");
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-screen__form" onSubmit={handleSubmit}>
        <h1 className="login-screen__title">AI Business Automation Studio</h1>
        {error && (
          <div className="banner banner--error" role="alert">
            <p>{error}</p>
          </div>
        )}
        <label className="field-label">
          Email
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="username"
            required
            autoFocus
          />
        </label>
        <label className="field-label">
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
