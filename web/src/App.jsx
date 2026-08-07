import { useEffect, useState } from "react";
import "./App.css";
import { api, UnauthenticatedError } from "./api";
import { ErrorState, Loading } from "./components";
import AdvisorView from "./views/AdvisorView";
import ChatHome from "./views/ChatHome";
import DecoderView from "./views/DecoderView";
import IntakeView from "./views/IntakeView";
import DemoLogin from "./views/DemoLogin";
import MissionView from "./views/MissionView";
import SequenceView from "./views/SequenceView";
import Login from "./views/Login";
import PlannerView from "./views/PlannerView";
import RegistrarView from "./views/RegistrarView";
import StudentView from "./views/StudentView";

/**
 * The view is decided by who is signed in, not by a switcher. Each role lands on its own
 * question; an advisor can additionally drill into an advisee's dashboard (the API
 * enforces that it really is their advisee).
 */

const ROLE_QUESTIONS = {
  student: "Am I ready to register?",
  advisor: "Who needs me this week?",
  registrar: "Where is the pressure?",
  finance: "Which financial cases need review?",
};

export default function App() {
  const [me, setMe] = useState(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState(null);
  // Advisor drill-down into one advisee; null means "own home view".
  const [viewStudentId, setViewStudentId] = useState(null);
  // Student tabs. The chat is the front door — it greets from computed state, answers on
  // first contact with nothing entered, and renders the agent's work as actionable cards.
  // The other views survive as the "I want to look at the records myself" path, and the
  // conditional landing logic they used to need is gone: the greeting does that job now.
  const [studentTab, setStudentTab] = useState("chat");

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
      setViewStudentId(null);
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

  // Signed out: two doors. `/demo` is the portfolio entrance with seeded roles; anything
  // else is the real sign-in. A router would be three routes' worth of dependency for a
  // decision that is one string comparison — the links between the two pages are plain
  // navigations, which is correct behaviour for a login screen anyway.
  if (!me) {
    return window.location.pathname.startsWith("/demo") ? <DemoLogin /> : <Login />;
  }

  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>

      <header className="topbar">
        <div className="topbar__inner">
          <div className="brand">
            <span className="brand__mark" aria-hidden="true" />
            <div className="brand__text">
              <span className="brand__name">UAX</span>
              <span className="brand__sub">Unified Academic Experience</span>
            </div>
          </div>

          <div className="whoami">
            <div className="whoami__text">
              <span className="whoami__name">{me.full_name}</span>
              <span className="whoami__role">
                {me.role}
                {me.office ? ` · ${me.office}` : ""}
                {me.student_number ? ` · ${me.student_number}` : ""}
              </span>
            </div>
            <button type="button" className="btn" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>
      </header>

      <div className="subbar">
        <div className="subbar__inner">
          <p className="subbar__question">{ROLE_QUESTIONS[me.role] ?? ""}</p>
          {me.role === "student" ? (
            <nav className="roles" aria-label="Student views">
              {[
                ["chat", "Assistant"],
                ["intake", "Add from transcript"],
                ["decoder", "Decode an error"],
                ["mission", "Registration mission"],
                ["sequence", "Term sequence"],
                ["planner", "Degree planner"],
                ...(me.student_id ? [["dashboard", "Dashboard (demo)"]] : []),
              ].map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={`role ${studentTab === id ? "role--active" : ""}`}
                  aria-current={studentTab === id ? "page" : undefined}
                  onClick={() => setStudentTab(id)}
                >
                  {label}
                </button>
              ))}
            </nav>
          ) : null}
          {viewStudentId ? (
            <button type="button" className="btn" onClick={() => setViewStudentId(null)}>
              ← Back to my queue
            </button>
          ) : null}
        </div>
      </div>

      <main id="main" className="main">
        {me.role === "student" ? (
          studentTab === "chat" ? (
            <ChatHome me={me} onOpenView={setStudentTab} />
          ) : studentTab === "intake" ? (
            <IntakeView onOpenView={setStudentTab} />
          ) : studentTab === "decoder" ? (
            <DecoderView onOpenPlanner={() => setStudentTab("planner")} />
          ) : studentTab === "mission" ? (
            <MissionView onOpenPlanner={() => setStudentTab("planner")} />
          ) : studentTab === "sequence" ? (
            <SequenceView onOpenPlanner={() => setStudentTab("planner")} />
          ) : me.student_id && studentTab === "dashboard" ? (
            <StudentView studentId={me.student_id} />
          ) : (
            <PlannerView />
          )
        ) : null}

        {me.role === "advisor" ? (
          viewStudentId ? (
            <StudentView studentId={viewStudentId} />
          ) : (
            <AdvisorView onOpenStudent={setViewStudentId} />
          )
        ) : null}

        {me.role === "registrar" ? <RegistrarView /> : null}

        {me.role === "finance" ? <FinanceView /> : null}
      </main>

      {/* The floating Ask UAX panel is gone: the assistant is the front door now, not an
          accessory docked in a corner. AskAlbert.jsx stays in the tree for reference until
          Phase B settles what the chat keeps from it. */}

      <footer className="footer">
        <p>
          Personal portfolio project. All students, records, and policies are fictional or
          quoted from public NYU bulletins with source links. Not an official NYU system —
          Albert is always authoritative.
        </p>
      </footer>
    </>
  );
}

/** Minimal finance view: the financial case queue the API scopes for this role. */
function FinanceView() {
  const [cases, setCases] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.cases().then(setCases).catch((err) => setError(err.message));
  }, []);

  if (error) return <ErrorState message={error} />;
  if (!cases) return <Loading what="financial cases" />;

  return (
    <div className="stack">
      <section className="card">
        <p className="eyebrow">Financial cases</p>
        <h2>Holds & aid disputes</h2>
        {cases.length === 0 ? (
          <p className="muted">No open financial cases.</p>
        ) : (
          <ul className="cases">
            {cases.map((item) => (
              <li key={item.id} className="case">
                <div className="case__head">
                  <span className="case__number">{item.case_number}</span>
                  <span className={`tag tag--${item.status === "resolved" ? "good" : "warn"}`}>
                    {item.status_label}
                  </span>
                </div>
                <p className="case__title">{item.title}</p>
                <p className="muted">
                  {item.student_name} · {item.category.replace(/_/g, " ")}
                </p>
                {item.ai_summary ? (
                  <div className="case__summary">
                    <span className="case__summary-label">Assistant summary</span>
                    <p>{item.ai_summary}</p>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
