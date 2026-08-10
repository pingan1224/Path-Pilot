import { useEffect, useState } from "react";
import "./App.css";
import { api, UnauthenticatedError } from "./api";
import { ErrorState, Loading } from "./components";
import DemoLogin from "./views/DemoLogin";
import Login from "./views/Login";
import StudentShell from "./views/StudentShell";

/**
 * UAX is a student product. It used to be four: a student workspace plus an advisor
 * queue, a registrar pressure board, and a finance case list, each landing on its own
 * question. Those three are gone — not hidden behind a flag, deleted — because carrying
 * three staff surfaces meant every change to the student experience had to be paid for
 * three more times, and none of them was the thing this product is for.
 *
 * What survives from that decision is the scoping, not the roles: the API still resolves
 * identity from the session cookie and still refuses to serve one student another
 * student's record. The `advisor` on a student's record is now what it always was in
 * practice — the human the handoff email is addressed to, not a login.
 */

export default function App() {
  const [me, setMe] = useState(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch((err) => {
        if (!(err instanceof UnauthenticatedError)) setError(err.message);
      })
      .finally(() => setChecking(false));
  }, []);

  async function signOut() {
    try {
      await api.logout();
    } finally {
      setMe(null);
    }
  }

  if (checking) {
    return (
      <main id="main" className="main">
        <Loading what="UAX" />
      </main>
    );
  }

  if (error) {
    return (
      <main id="main" className="main">
        <ErrorState message={error} onRetry={() => window.location.reload()} />
      </main>
    );
  }

  // Signed out: two doors. `/demo` is the portfolio entrance with seeded students; anything
  // else is the real sign-in. A router would be three routes' worth of dependency for a
  // decision that is one string comparison — the links between the two pages are plain
  // navigations, which is correct behaviour for a login screen anyway.
  if (!me) {
    return window.location.pathname.startsWith("/demo") ? <DemoLogin /> : <Login />;
  }

  // A non-student account can still hold a valid session from a database seeded before the
  // staff views were removed. Saying so beats rendering a workspace with no record behind
  // it — rule 6: name what is missing rather than failing quietly.
  if (me.role !== "student") {
    return (
      <main id="main" className="main">
        <div className="state state--error" role="alert">
          <p>
            UAX is a student workspace, and {me.full_name} is signed in as {me.role}. Sign
            out and use a student account.
          </p>
          <button type="button" className="btn" onClick={signOut}>
            Sign out
          </button>
        </div>
      </main>
    );
  }

  return <StudentShell me={me} onSignOut={signOut} />;
}
