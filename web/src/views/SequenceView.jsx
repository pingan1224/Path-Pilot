import { useEffect, useState } from "react"
import { api } from "@/api"
import { Finding } from "@/components/Finding"
import {
  ErrorNote,
  Eyebrow,
  INPUT_CLASS,
  Muted,
  ProgramNotice,
  Tone,
  WarnNote,
  isProgramIssue,
} from "@/components/nocturne"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

/**
 * The sequence planner: what order the remaining requirements can be taken in.
 *
 * The layout is arranged around one risk. A term-by-term schedule is the most
 * authoritative-looking thing this product produces — it is a grid, it has dates, and a
 * student will screenshot it and plan a year around it. But a third of the catalog does not
 * say when its courses run, the per-term credit cap is the student's own number rather than a
 * published rule for this program, and an open-ended elective is a placeholder with no
 * prerequisites checked.
 *
 * So each placement carries its own basis inline — "offered Fall, Spring" against "the
 * bulletin does not say when this runs" — rather than one disclaimer under the grid. A
 * caveat averaged across the whole plan tells the student nothing about which two courses
 * are the shaky ones, and those are exactly the two they need to go and check.
 *
 * When nothing fits, the binding constraint takes the position the grid would have had.
 * "No sequence works" is nearly useless; "the finish date is the only thing in the way, and
 * one more term fixes it" is the answer.
 */

const BASIS_META = {
  published: { tone: "good", label: "Published" },
  irregular: { tone: "warn", label: "Runs irregularly" },
  unstated: { tone: "neutral", label: "Term is a guess" },
}

const CREDIT_CHOICES = [3, 6, 9, 12]

export default function SequenceView({ onOpenPlanner, onOpenProgram }) {
  const [startTerm, setStartTerm] = useState("")
  const [deadline, setDeadline] = useState("")
  const [maxCredits, setMaxCredits] = useState("")
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function load(overrides = {}) {
    setBusy(true)
    setError(null)
    try {
      setPlan(
        await api.sequence({
          startTerm: overrides.startTerm ?? startTerm,
          deadline: overrides.deadline ?? deadline,
          maxCredits: overrides.maxCredits ?? maxCredits,
        }),
      )
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error && !plan) {
    return (
      <div className="flex flex-col items-start gap-3">
        {isProgramIssue(error.code) ? (
          <ProgramNotice
            code={error.code}
            message={error.message}
            onChooseProgram={onOpenProgram}
          />
        ) : (
          <>
            <ErrorNote>Could not compute a sequence: {error.message}</ErrorNote>
            <Button variant="outline" size="sm" onClick={() => load()}>
              Try again
            </Button>
          </>
        )}
      </div>
    )
  }
  if (!plan) {
    return (
      <p role="status" className="text-body text-muted-foreground">
        Solving your sequence…
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {error ? <ErrorNote>{error.message}</ErrorNote> : null}

      <Card>
        <CardHeader>
          <Eyebrow>Remaining requirements</Eyebrow>
          <CardTitle>What order can I take these in?</CardTitle>
          <CardDescription>
            Prerequisite order, when the bulletin says each course runs, how many credits you
            will carry, one concentration finished in full, and a term to finish by — solved
            together, because that is the part you cannot do on paper.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              load()
            }}
          >
            <label className="flex min-w-[150px] flex-1 flex-col gap-1 text-meta text-muted-foreground">
              Starting term
              <input
                className={INPUT_CLASS}
                value={startTerm}
                onChange={(e) => setStartTerm(e.target.value)}
                placeholder={plan.start_term}
                disabled={busy}
              />
            </label>
            <label className="flex min-w-[150px] flex-1 flex-col gap-1 text-meta text-muted-foreground">
              Finish by (optional)
              <input
                className={INPUT_CLASS}
                value={deadline}
                onChange={(e) => setDeadline(e.target.value)}
                placeholder="e.g. Spring 2028"
                disabled={busy}
              />
            </label>
            <label className="flex min-w-[130px] flex-col gap-1 text-meta text-muted-foreground">
              Credits per term
              <select
                className={INPUT_CLASS}
                value={maxCredits}
                onChange={(e) => {
                  setMaxCredits(e.target.value)
                  load({ maxCredits: e.target.value })
                }}
                disabled={busy}
              >
                <option value="">{plan.max_credits_per_term} (assumed)</option>
                {CREDIT_CHOICES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <Button type="submit" disabled={busy}>
              {busy ? "Solving…" : "Recalculate"}
            </Button>
          </form>

          <p className="text-meta leading-relaxed text-subtle">{plan.disclaimer}</p>
        </CardContent>
      </Card>

      {plan.feasible ? (
        <Schedule plan={plan} />
      ) : (
        <Blocked plan={plan} onOpenPlanner={onOpenPlanner} />
      )}

      {plan.rejected_tracks.length > 0 ? (
        <Card>
          <CardHeader>
            <Eyebrow>Concentrations that do not fit</Eyebrow>
            <CardTitle>Other tracks</CardTitle>
            <CardDescription>
              You are free to change concentration, so each one was tried. These could not be
              sequenced under the same constraints.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="findings">
              {plan.rejected_tracks.map((t) => (
                <Finding
                  key={t.track}
                  verdict="conditional"
                  label="Does not fit"
                  summary={t.track}
                  detail={t.why}
                />
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <Assumptions plan={plan} onOpenPlanner={onOpenPlanner} />
    </div>
  )
}

/* ---------------------------------------------------------------------------------- */

function Schedule({ plan }) {
  const guesses = plan.terms
    .flatMap((t) => t.courses)
    .filter((c) => c.offering_basis !== "published").length

  return (
    <Card className="border-primary/30">
      <CardHeader>
        <Eyebrow>
          {plan.chosen_track ? `Concentration: ${plan.chosen_track}` : "Sequence"}
        </Eyebrow>
        <CardTitle className="nx-statement text-title">
          {plan.terms_needed} more term{plan.terms_needed === 1 ? "" : "s"}, finishing{" "}
          {plan.finish_term}
        </CardTitle>
        <CardDescription>
          {guesses === 0
            ? "Every placement matches a term the bulletin publishes for that course."
            : `${guesses} placement${guesses === 1 ? "" : "s"} sit in a term the bulletin does not confirm — marked below.`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {/* The wide tier: terms sit side by side where the width exists, without ever
            becoming a dashboard grid — each cell is still the same list a phone gets. */}
        <ol className="grid list-none gap-3 sm:grid-cols-2">
          {plan.terms.map((term) => (
            <li
              key={term.term}
              className="flex flex-col gap-2 rounded-md border border-border bg-muted/40 p-3"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-body font-medium">{term.term}</span>
                <span className="text-meta text-muted-foreground">
                  {term.credits} credits
                </span>
              </div>
              <ul className="flex list-none flex-col gap-2">
                {term.courses.map((course) => {
                  const meta = BASIS_META[course.offering_basis] ?? BASIS_META.unstated
                  return (
                    <li
                      key={course.course_code}
                      className="flex flex-col gap-1 rounded-md bg-card p-2.5"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm">{course.course_code}</span>
                        <Tone tone={meta.tone}>{meta.label}</Tone>
                      </div>
                      <p className="text-body leading-snug">{course.title}</p>
                      <p className="text-meta leading-relaxed text-muted-foreground">
                        {course.requirement ? `${course.requirement} · ` : ""}
                        {course.credits} cr · {course.offering_note}
                        {course.offering_source ? ` (“${course.offering_source}”)` : ""}
                      </p>
                    </li>
                  )
                })}
              </ul>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}

function Blocked({ plan, onOpenPlanner }) {
  const why = plan.infeasibility
  return (
    <Card className="border-primary/45">
      <CardHeader>
        <Eyebrow>No order fits</Eyebrow>
        <CardTitle>What is standing in the way</CardTitle>
        <CardDescription>{why?.explanation}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {why?.binding_labels?.length ? (
          <>
            <Eyebrow>Any one of these would unblock it</Eyebrow>
            <ul className="findings">
              {why.binding_labels.map((label, i) => (
                <Finding
                  key={label}
                  verdict="conditional"
                  label="Binding"
                  summary={label}
                  detail={why.remedies[i] ?? null}
                />
              ))}
            </ul>
            <Muted>
              Each of these was established by removing it and re-solving — not inferred.
            </Muted>
          </>
        ) : null}

        {onOpenPlanner ? (
          <div>
            <Button variant="outline" onClick={onOpenPlanner}>
              Check my record →
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function Assumptions({ plan, onOpenPlanner }) {
  if (plan.assumptions.length === 0 && plan.unplaceable.length === 0) return null

  return (
    <Card>
      <CardHeader>
        <Eyebrow>What this rests on</Eyebrow>
        <CardTitle>Assumptions</CardTitle>
        <CardDescription>
          The sequence above is only as good as these. None of them is a rule Path Pilot could
          verify.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <ul className="findings">
          {plan.assumptions.map((a) => (
            /* "Assumed" rather than the default "Ask a human": the check line below already
               names who to ask, and this card is about what the sequence rests on. */
            <Finding
              key={a.subject}
              verdict="unverifiable"
              label="Assumed"
              summary={a.subject}
              detail={a.statement}
              nextStep={a.check}
            />
          ))}
        </ul>
        {plan.unplaceable.length > 0 ? (
          <WarnNote>
            Left out of the sequence entirely, because they are not in the catalog Path Pilot has
            loaded: {plan.unplaceable.join(", ")}.
          </WarnNote>
        ) : null}
        {onOpenPlanner ? (
          <div>
            <Button variant="outline" onClick={onOpenPlanner}>
              Edit my record →
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
