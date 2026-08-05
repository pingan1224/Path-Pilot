import { useState } from "react";
import { api } from "../api";

/**
 * The demo door.
 *
 * One click signs in as a seeded role. The password is printed because every account here
 * is fictional and the whole point is that a visitor can enter each role and check the
 * permission boundaries from both sides — sign in as a student, fail to reach the
 * registrar dashboard, sign in as the registrar, succeed.
 *
 * These buttons are not an auth bypass: they submit the same credentials to the same
 * endpoint, and the server still hashes, verifies, and issues a session.
 */

const DEMO_PASSWORD = "uax-demo-2026";

const ACCOUNTS = [
  {
    role: "Student",
    name: "Alex Chen",
    email: "alex.chen@uax.example.edu",
    hint: "An aid hold is blocking registration, and its deadline lands before the window opens.",
  },
  {
    role: "Student",
    name: "Diego Morales",
    email: "diego.morales@uax.example.edu",
    hint: "27 credits earned, but only 21 count toward the degree.",
  },
  {
    role: "Advisor",
    name: "Maya Patel",
    email: "maya.patel@uax.example.edu",
    hint: "25 advisees sorted into triage groups, with case actions.",
  },
  {
    role: "Registrar",
    name: "Jordan Lee",
    email: "jordan.lee@uax.example.edu",
    hint: "Capacity pressure and why registrations are failing.",
  },
  {
    role: "Finance",
    name: "Sam Okafor",
    email: "sam.okafor@uax.example.edu",
    hint: "Financial cases only — the other categories are not visible to this role.",
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
            <span className="brand__name">UAX</span>
            <span className="brand__sub">Demo mode</span>
          </div>
        </div>

        <p className="login__pitch">
          Every student, hold, and case below is invented. Policy text is quoted from
          public NYU bulletins with source links. Pick a role — each one lands on a
          different question, and each is blocked from the others&rsquo; data.
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
                <span className="demo__role">{account.role}</span>
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
