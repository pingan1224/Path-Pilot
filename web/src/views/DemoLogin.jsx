import { useState } from "react";
import { api } from "../api";

/**
 * The demo door.
 *
 * One click signs in as a seeded student. The password is printed because every account
 * here is fictional and the whole point is that a visitor can walk in and see the product
 * on a record that already has something wrong with it — an aid hold, or credits that do
 * not count — rather than an empty account.
 *
 * Two students rather than one because the interesting behaviour is the difference: the
 * same screens have to say two different true things, and neither can see the other's
 * record.
 *
 * These buttons are not an auth bypass: they submit the same credentials to the same
 * endpoint, and the server still hashes, verifies, and issues a session.
 */

const DEMO_PASSWORD = "path-pilot-demo-2026";

// The chip used to name the role, back when there were four. With only students left it
// would read "Student" twice, so it names the situation instead — the thing that actually
// differs between these two doors.
const ACCOUNTS = [
  {
    situation: "Blocked",
    name: "Alex Chen",
    email: "alex.chen@pathpilot.example.edu",
    hint: "An aid hold is blocking registration, and its deadline lands before the window opens.",
  },
  {
    situation: "Off track",
    name: "Diego Morales",
    email: "diego.morales@pathpilot.example.edu",
    hint: "27 credits earned, but only 21 count toward the degree.",
  },
];

export default function DemoLogin() {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  async function enter(email) {
    setBusy(email);
    setError(null);
    try {
      await api.login(email, DEMO_PASSWORD);
      window.location.assign("/");
    } catch (err) {
      setError(err.message);
      setBusy(null);
    }
  }

  return (
    <main id="main" className="login">
      <section className="login__card login__card--demo">
        <div className="brand brand--large">
          <span className="brand__mark" aria-hidden="true" />
          <div className="brand__text">
            <span className="brand__name">Path Pilot</span>
            <span className="brand__sub">Demo mode</span>
          </div>
        </div>

        <p className="login__pitch">
          Every student, hold, and case below is invented. Policy text is quoted from
          public NYU bulletins with source links. Pick a student — each one walks in with
          a different problem, and neither can reach the other&rsquo;s record.
        </p>

        {error ? (
          <p className="login__error" role="alert">
            {error}
          </p>
        ) : null}

        <ul className="demo__list">
          {ACCOUNTS.map((account) => (
            <li key={account.email}>
              <button
                type="button"
                className="demo__btn"
                disabled={busy !== null}
                onClick={() => enter(account.email)}
              >
                <span className="demo__role">{account.situation}</span>
                <span className="demo__name">
                  {busy === account.email ? "Signing in…" : account.name}
                </span>
                <span className="demo__hint">{account.hint}</span>
              </button>
            </li>
          ))}
        </ul>

        <p className="login__alt">
          Password for all demo accounts: <code>{DEMO_PASSWORD}</code> ·{" "}
          <a href="/">Real sign-in</a>
        </p>

        <p className="login__legal">
          Not affiliated with New York University. Independent personal project.
        </p>
      </section>
    </main>
  );
}
