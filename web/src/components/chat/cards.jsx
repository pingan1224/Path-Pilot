import { useState } from "react"
import { api } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"

/**
 * Inline tool-result cards for the chat surface.
 *
 * The design decision that shapes every component here: cards render **authoritative
 * current state fetched after the turn**, not a snapshot of what the tool returned
 * mid-conversation. ChatHome re-fetches the mission / re-runs the deterministic sequence
 * and decoder endpoints once the answer lands, and hands the results in as props. That is
 * the same "no stored status, recompute on read" rule the mission engine lives by — a
 * card the student acts on must never disagree with the page they would see elsewhere.
 *
 * And the buttons are real. "Add to my plan" calls the same student-authenticated
 * endpoint the Mission page uses, and the server's recomputed mission replaces the card
 * state. Before this file existed, the agent's one actionable output — a proposed course
 * — was invisible in the chat that produced it; acting on it meant finding another tab.
 */

const TERM_SUGGESTIONS = ["Fall 2026", "Spring 2027", "Summer 2027"]

const STEP_LABEL = {
  profile: "Enter your record",
  gaps: "Review degree gaps",
  candidates: "Choose courses",
  open_items: "Settle open items",
  handoff: "Advisor handoff",
}

/** Mission state with actionable proposals; also covers the "no mission yet" case. */
export function MissionCard({ mission: initial, onOpenView }) {
  const [mission, setMission] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function act(fn) {
    setBusy(true)
    setError(null)
    try {
      setMission(await fn())
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // No mission on the account. Starting one is a student action — the agent cannot do
  // this (see the mission service), so the card offers the click rather than doing it.
  if (!mission) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No registration mission yet</CardTitle>
          <CardDescription>
            A mission tracks your preparation for one term — courses chosen, blockers
            settled, a summary for your advisor. Pick a term to start one.
          </CardDescription>
        </CardHeader>
        <CardFooter className="flex-wrap gap-2">
          {TERM_SUGGESTIONS.map((term) => (
            <Button
              key={term}
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => act(() => api.createMission(term))}
            >
              {term}
            </Button>
          ))}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </CardFooter>
      </Card>
    )
  }

  const done = mission.steps.filter((s) => s.state === "done").length
  const active = mission.steps.find((s) => s.state === "active")
  const proposals = mission.candidates.filter((c) => c.state === "proposed")
  const chosen = mission.candidates.filter((c) => c.state === "confirmed")

  return (
    <Card className="border-primary/30">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Registration mission — {mission.term}
          {mission.complete ? <Badge>Complete</Badge> : null}
          {/* Badged so nobody is surprised to find a container they did not create. The
              term is the only thing the assistant chose, and it is changeable. */}
          {mission.created_by === "ai" ? (
            <Badge variant="outline">Started by the assistant</Badge>
          ) : null}
        </CardTitle>
        <CardDescription>
          {done} of {mission.steps.length} steps done
          {active ? ` · now: ${STEP_LABEL[active.id] ?? active.title}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Progress value={(done / mission.steps.length) * 100} />

        {proposals.length > 0 ? (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium">
                Suggested — not in your plan until you confirm:
              </p>
              {/* One click for a whole one-shot proposal. Still one deliberate act per
                  batch, and each course keeps its own buttons for picking selectively —
                  batching the click must not blur what was agreed to. */}
              {proposals.length > 1 ? (
                <Button
                  size="xs"
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      let latest = mission
                      for (const c of proposals) {
                        latest = await api.missionDecideCandidate(mission.id, c.id, true)
                      }
                      return latest
                    })
                  }
                >
                  Add all {proposals.length}
                </Button>
              ) : null}
            </div>
            {proposals.map((c) => (
              <div
                key={c.id}
                className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 p-2"
              >
                <span className="font-mono text-sm">{c.course_code}</span>
                {c.rationale ? (
                  <span className="min-w-0 flex-1 text-sm text-muted-foreground">
                    {c.rationale}
                  </span>
                ) : null}
                <span className="flex gap-1.5">
                  <Button
                    size="xs"
                    disabled={busy}
                    onClick={() =>
                      act(() => api.missionDecideCandidate(mission.id, c.id, true))
                    }
                  >
                    Add to my plan
                  </Button>
                  <Button
                    size="xs"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      act(() => api.missionDecideCandidate(mission.id, c.id, false))
                    }
                  >
                    No thanks
                  </Button>
                </span>
              </div>
            ))}
          </div>
        ) : null}

        {chosen.length > 0 ? (
          <p className="text-sm text-muted-foreground">
            Chosen: {chosen.map((c) => c.course_code).join(", ")}
          </p>
        ) : null}

        {mission.open_blockers.length > 0 ? (
          <p className="text-sm text-destructive">
            {mission.open_blockers.length} unresolved blocker
            {mission.open_blockers.length === 1 ? "" : "s"} on your chosen courses.
          </p>
        ) : null}

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </CardContent>
      <CardFooter>
        <Button size="sm" variant="ghost" onClick={() => onOpenView?.("mission")}>
          Open the full mission →
        </Button>
      </CardFooter>
    </Card>
  )
}

const BASIS_BADGE = {
  published: { variant: "secondary", label: "Published" },
  irregular: { variant: "outline", label: "Irregular — guess" },
  unstated: { variant: "outline", label: "Term is a guess" },
}

/** Compact term-by-term schedule, or the binding constraint when nothing fits. */
export function SequenceCard({ plan, onOpenView }) {
  if (!plan.feasible) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No sequence fits</CardTitle>
          <CardDescription>{plan.infeasibility?.explanation}</CardDescription>
        </CardHeader>
        {plan.infeasibility?.remedies?.length ? (
          <CardContent className="flex flex-col gap-1.5">
            {plan.infeasibility.remedies.map((remedy, i) => (
              <p key={i} className="text-sm text-muted-foreground">
                • {remedy}
              </p>
            ))}
          </CardContent>
        ) : null}
        <CardFooter>
          <Button size="sm" variant="ghost" onClick={() => onOpenView?.("sequence")}>
            Adjust the constraints →
          </Button>
        </CardFooter>
      </Card>
    )
  }

  const guesses = plan.terms
    .flatMap((t) => t.courses)
    .filter((c) => c.offering_basis !== "published").length

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {plan.terms_needed} term{plan.terms_needed === 1 ? "" : "s"}, finishing{" "}
          {plan.finish_term}
        </CardTitle>
        <CardDescription>
          {plan.chosen_track ? `Concentration: ${plan.chosen_track} · ` : ""}
          {plan.max_credits_per_term} credits/term
          {plan.credit_cap_was_assumed ? " (assumed)" : ""}
          {guesses > 0
            ? ` · ${guesses} placement${guesses === 1 ? "" : "s"} in unconfirmed terms`
            : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {plan.terms.map((term) => (
          <div key={term.term} className="rounded-md border bg-muted/40 p-2">
            <p className="text-sm font-semibold">
              {term.term}{" "}
              <span className="font-normal text-muted-foreground">
                · {term.credits} cr
              </span>
            </p>
            <div className="mt-1 flex flex-col gap-1">
              {term.courses.map((course) => {
                const badge = BASIS_BADGE[course.offering_basis] ?? BASIS_BADGE.unstated
                return (
                  <p
                    key={course.course_code}
                    className="flex flex-wrap items-center gap-2 text-sm"
                  >
                    <span className="font-mono">{course.course_code}</span>
                    <Badge variant={badge.variant}>{badge.label}</Badge>
                  </p>
                )
              })}
            </div>
          </div>
        ))}
        {plan.assumptions.length > 0 ? (
          <p className="text-sm text-muted-foreground">
            Rests on {plan.assumptions.length} assumption
            {plan.assumptions.length === 1 ? "" : "s"} — check them before relying on
            this.
          </p>
        ) : null}
      </CardContent>
      <CardFooter>
        <Button size="sm" variant="ghost" onClick={() => onOpenView?.("sequence")}>
          Open the full sequence →
        </Button>
      </CardFooter>
    </Card>
  )
}

const OUTCOME_BADGE = {
  identified: { variant: "default", label: "Cause identified" },
  ambiguous: { variant: "secondary", label: "Needs one more detail" },
  unrecognized: { variant: "outline", label: "Could not decode" },
}

/** Compact decoded-error result with the follow-up question when there is one. */
export function DecodeCard({ decoded, onOpenView }) {
  const badge = OUTCOME_BADGE[decoded.outcome] ?? OUTCOME_BADGE.unrecognized
  const followUp = decoded.follow_ups?.[0]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {decoded.reason_label ?? "Registration error"}
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </CardTitle>
        {decoded.reading ? <CardDescription>{decoded.reading}</CardDescription> : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {decoded.outcome === "ambiguous" && decoded.candidates?.length > 1 ? (
          <p className="text-sm text-muted-foreground">
            Consistent with: {decoded.candidates.slice(0, 2).map((c) => c.label).join(" — or — ")}
          </p>
        ) : null}
        {followUp ? (
          <p className="text-sm">
            <span className="font-medium">To narrow it down:</span> {followUp.question}
          </p>
        ) : null}
        {decoded.responsible_office ? (
          <p className="text-sm text-muted-foreground">
            Who can act: {decoded.responsible_office.replace(/_/g, " ")}
          </p>
        ) : null}
      </CardContent>
      <CardFooter>
        <Button size="sm" variant="ghost" onClick={() => onOpenView?.("decoder")}>
          Open the full decoder →
        </Button>
      </CardFooter>
    </Card>
  )
}
