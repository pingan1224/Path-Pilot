import { useEffect, useState } from "react";
import "./App.css";
import { api } from "./api";
import { ErrorState, Loading } from "./components";
import AdvisorView from "./views/AdvisorView";
import AskAlbert from "./views/AskAlbert";
import RegistrarView from "./views/RegistrarView";
import StudentView from "./views/StudentView";

const ROLES = [
  { id: "student", label: "Student", question: "Am I ready to register?" },
  { id: "advisor", label: "Advisor", question: "Who needs me this week?" },
  { id: "registrar", label: "Registrar", question: "Where is the pressure?" },
];

// The three hand-authored scenarios, surfaced first in the picker so the demo does not
// start on a randomly generated student.
const FEATURED = ["Alex Chen", "Priya Raman", "Diego Morales"];

export default function App() {
  const [role, setRole] = useState("student");
  const [students, setStudents] = useState([]);
  const [advisors, setAdvisors] = useState([]);
  const [studentId, setStudentId] = useState(null);
  const [advisorId, setAdvisorId] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  async function bootstrap() {
    setLoading(true);
    setError(null);
    try {
      const [studentList, advisorList] = await Promise.all([api.students(), api.advisors()]);
      const featured = FEATURED.map((name) =>
        studentList.find((s) => s.full_name === name),
      ).filter(Boolean);
      const rest = studentList.filter((s) => !FEATURED.includes(s.full_name));
      const ordered = [...featured, ...rest];

      setStudents(ordered);
      setAdvisors(advisorList);
      setStudentId(ordered[0]?.id ?? null);
      setAdvisorId(advisorList[0]?.id ?? null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    bootstrap();
  }, []);

  function openStudent(id) {
    setStudentId(id);
    setRole("student");
  }

  const activeRole = ROLES.find((r) => r.id === role);

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

          <nav className="roles" aria-label="Select a role">
            {ROLES.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`role ${role === item.id ? "role--active" : ""}`}
                aria-current={role === item.id ? "page" : undefined}
                onClick={() => setRole(item.id)}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <div className="subbar">
        <div className="subbar__inner">
          <p className="subbar__question">{activeRole?.question}</p>

          {role === "student" && students.length > 0 ? (
            <label className="picker">
              <span>Viewing as</span>
              <select value={studentId ?? ""} onChange={(e) => setStudentId(Number(e.target.value))}>
                {students.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.full_name} · {s.student_number}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          {role === "advisor" && advisors.length > 0 ? (
            <label className="picker">
              <span>Viewing as</span>
              <select value={advisorId ?? ""} onChange={(e) => setAdvisorId(Number(e.target.value))}>
                {advisors.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.full_name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      </div>

      <main id="main" className="main">
        {loading ? <Loading what="UAX" /> : null}
        {error ? <ErrorState message={error} onRetry={bootstrap} /> : null}
        {!loading && !error ? (
          <>
            {role === "student" && studentId ? <StudentView studentId={studentId} /> : null}
            {role === "advisor" && advisorId ? (
              <AdvisorView advisorId={advisorId} onOpenStudent={openStudent} />
            ) : null}
            {role === "registrar" ? <RegistrarView /> : null}
          </>
        ) : null}
      </main>

      {/* Non-modal by rule: the dashboard stays visible while the assistant is open. */}
      {role === "student" && studentId ? <AskAlbert studentId={studentId} /> : null}

      <footer className="footer">
        <p>
          Portfolio project. All students, records, and policies are fictional. Not affiliated
          with any university.
        </p>
      </footer>
    </>
  );
}
