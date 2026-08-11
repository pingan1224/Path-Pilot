import { useEffect, useMemo, useState } from "react"
import { api } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

/**
 * Which program the student is in.
 *
 * This exists because the answer used to be assumed. Every real user was planned against
 * the one program whose requirements had been encoded, so a student in Global Affairs got
 * a degree audit for Management & Analytics — correctly cited, internally consistent, and
 * about somebody else's degree. The picker is how they say something true instead.
 *
 * The screen's job is therefore not "choose an option" but "understand what changes". Most
 * programs on this list are **listed but not encoded**: the bulletin names them, nobody has
 * transcribed their requirements, and this tool cannot audit a degree it has not read. That
 * is stated up front, per program, rather than discovered later as a page that refuses —
 * the same reason a stale record here carries its age instead of a fresh-looking number.
 *
 * Capability is never signalled by colour alone: an unencoded program is labelled
 * "Policy answers only" in words, next to the badge.
 */

// What each capability means to a student, in their words rather than the API's.
const CAPABILITY_LABEL = {
  policy_answers: "Answers from published policy, with sources",
  error_decoding: "Registration error decoding",
  albert_checklist: "What to check in Albert",
  degree_audit: "Degree progress against your requirements",
  course_sequence: "Term-by-term sequence planning",
  registration_mission: "Registration missions",
}

export default function ProgramView({ current, onChanged }) {
  const [programs, setPrograms] = useState(null)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(null)
  const [query, setQuery] = useState("")

  useEffect(() => {
    let cancelled = false
    api
      .programs()
      .then((rows) => {
        if (!cancelled) setPrograms(rows)
      })
      .catch((err) => {
        // A failed read is its own state. Rendering an empty list would read as "your
        // school offers no programs", which is a claim this screen is in no position
        // to make.
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    if (!programs) return []
    const needle = query.trim().toLowerCase()
    if (!needle) return programs
    return programs.filter((p) => p.name.toLowerCase().includes(needle))
  }, [programs, query])

  async function choose(program) {
    setSaving(program.code)
    setError(null)
    try {
      const updated = await api.setProgram(program.code)
      await onChanged?.(updated)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(null)
    }
  }

  const encodedCount = programs?.filter((p) => p.is_encoded).length ?? 0

  return (
    <section aria-labelledby="program-heading" className="flex flex-col gap-5">
      <div>
        <h1 id="program-heading" className="nx-statement text-title">
          Your program
        </h1>
        <p className="mt-1 max-w-[62ch] text-body text-muted-foreground">
          Path Pilot applies the published rules for the program you are actually in. Tell it
          which one so it never checks your record against somebody else&rsquo;s degree.
        </p>
      </div>

      {current ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              {current.program_name}
              <Badge variant={current.is_encoded ? "default" : "secondary"}>
                {current.is_encoded ? "Full support" : "Policy answers only"}
              </Badge>
            </CardTitle>
            <CardDescription>
              Currently selected · {current.level === "undergraduate" ? "Undergraduate" : "Graduate"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-1.5">
              {(current.capabilities ?? []).map((cap) => (
                <li key={cap} className="flex items-start gap-2 text-body">
                  <span className="nx-dot nx-dot--good mt-1.5" aria-hidden="true" />
                  <span>{CAPABILITY_LABEL[cap] ?? cap}</span>
                </li>
              ))}
            </ul>
            {!current.is_encoded ? (
              <p className="mt-3 max-w-[62ch] text-meta text-muted-foreground">
                Degree progress, sequencing and registration missions are unavailable for this
                program: its requirements have not been transcribed from the bulletin, and this
                tool will not check your record against rules it has not read.
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>No program selected</CardTitle>
            <CardDescription>
              Until you pick one, degree progress, sequencing and missions stay unavailable —
              they need to know which requirements apply to you.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {error ? (
        <div className="state state--error" role="alert">
          <p>{error}</p>
        </div>
      ) : null}

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="nx-label">
            {programs ? `${programs.length} programs` : "Programs"}
          </h2>
          {programs ? (
            <p className="text-micro text-subtle">
              {encodedCount} of {programs.length} have encoded requirements
            </p>
          ) : null}
        </div>

        <label className="sr-only" htmlFor="program-filter">
          Filter programs by name
        </label>
        <input
          id="program-filter"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by name…"
          className="w-full rounded-md border border-border bg-card px-3 py-2 text-body"
        />

        {programs === null && !error ? (
          <p className="text-body text-muted-foreground">Loading programs…</p>
        ) : null}

        {programs && filtered.length === 0 ? (
          <p className="text-body text-muted-foreground">
            No program matches “{query}”.
          </p>
        ) : null}

        <ul className="flex flex-col gap-px overflow-hidden rounded-md bg-border">
          {filtered.map((program) => {
            const isCurrent = current?.program_code === program.code
            return (
              <li
                key={program.code}
                className="flex flex-wrap items-center gap-x-3 gap-y-2 bg-card px-3.5 py-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-body leading-snug">{program.name}</div>
                  <div className="text-micro text-subtle">
                    {program.degree} ·{" "}
                    {program.is_encoded
                      ? `Full support · ${program.total_credits_required} credits`
                      : "Policy answers only — requirements not encoded"}
                  </div>
                </div>
                {isCurrent ? (
                  <Badge variant="outline">Selected</Badge>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={saving !== null}
                    onClick={() => choose(program)}
                  >
                    {saving === program.code ? "Saving…" : "Select"}
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
      </div>

      <p className="max-w-[68ch] text-meta text-subtle">
        Program names come from the NYU SPS bulletin. Undergraduate programs are not listed
        yet — that page is not part of the ingested corpus.
      </p>
    </section>
  )
}
