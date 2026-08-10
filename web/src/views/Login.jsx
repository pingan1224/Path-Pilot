import { useState } from "react";
import { api } from "../api";

/**
 * The real sign-in page.
 *
 * No demo accounts and no printed password here. Those live at /demo, because a page that
 * offers a real student "click here to become Alex Chen" reads as untrustworthy, and
 * mixing fictional identities into the same entry point as real ones is a bad habit to
 * start with. The demo is a separate door, clearly labelled.
 */
export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(email, password);
      // Full reload so the app re-bootstraps from /auth/me — one source of truth for
      // identity rather than threading the login response through component state.
      // Reload in place, not to "/": whoever followed a link to /mission and met this
      // page instead should land on the mission, or the deep link only works for
      // people who never needed it.
      window.location.reload();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <main id="main" className="login">
      <section className="login__card">
        <div className="brand brand--large">
          <span className="brand__mark" aria-hidden="true" />
          <div className="brand__text">
            <span className="brand__name">UAX</span>
            <span className="brand__sub">Unified Academic Experience</span>
          </div>
        </div>

        <p className="login__pitch">
          Registration readiness and academic planning for NYU SPS graduate students.
          An independent, read-only tool — Albert remains authoritative.
        </p>

        <form className="login__form" onSubmit={submit}>
          <label className="login__field">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label className="login__field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {error ? (
            <p className="login__error" role="alert">
              {error}
            </p>
          ) : null}
          <button type="submit" className="btn btn--primary login__submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="login__alt">
          Just looking around? <a href="/demo">Open the demo</a> — fictional data, no
          account needed.
        </p>

        <p className="login__legal">
          Not affiliated with New York University. Independent personal project.
        </p>
      </section>
    </main>
  );
}
