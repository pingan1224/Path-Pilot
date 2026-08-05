import { useState } from "react";
import { api } from "../api";

/**
 * Sign-in. The demo credentials are printed on the page on purpose: every account is
 * fictional, and the point of the demo is that a visitor can see each role's view and
 * verify the permission boundaries from both sides.
 */

const DEMO_ACCOUNTS = [
  { label: "Student", email: "alex.chen@uax.example.edu", hint: "aid hold blocking registration" },
  { label: "Student", email: "diego.morales@uax.example.edu", hint: "credits that don't all count" },
  { label: "Advisor", email: "maya.patel@uax.example.edu", hint: "triage queue of 25 advisees" },
  { label: "Registrar", email: "jordan.lee@uax.example.edu", hint: "capacity and failure dashboard" },
];

const DEMO_PASSWORD = "uax-demo-2026";

export default function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(emailValue, passwordValue) {
    setBusy(true);
    setError(null);
    try {
      const me = await api.login(emailValue, passwordValue);
      onLogin(me);
    } catch (err) {
      setError(err.message);
    } finally {
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
          A registration-readiness and academic-planning demo. All data is fictional; this
          is a personal project, not an NYU system.
        </p>

        <form
          className="login__form"
          onSubmit={(e) => {
            e.preventDefault();
            submit(email, password);
          }}
        >
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

        <div className="login__demo">
          <p className="login__demo-title">
            Demo accounts — password <code>{DEMO_PASSWORD}</code>
          </p>
          <ul>
            {DEMO_ACCOUNTS.map((account) => (
              <li key={account.email}>
                <button
                  type="button"
                  className="login__demo-btn"
                  disabled={busy}
                  onClick={() => submit(account.email, DEMO_PASSWORD)}
                >
                  <strong>{account.label}</strong>
                  <span className="mono">{account.email}</span>
                  <span className="muted">{account.hint}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </main>
  );
}
