import { useRef, useState } from "react"
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

/**
 * Transcript upload and review.
 *
 * The screen is arranged around one asymmetry: a row this tool reads *wrong* and the student
 * accepts puts coursework in their record they never took, and nothing downstream will catch
 * it — while a row it fails to read is merely missing, and visible. So the review is
 * per-row, opt-in, and everything uncertain is separated out with its reason attached rather
 * than mixed into a single "looks good" list.
 *
 * `matched` rows are pre-selected because the reader vouches for them entirely (code, term,
 * grade, and state all resolved). `needs_review` rows are deliberately NOT pre-selected: the
 * whole point of that state is that a person has to look. Selecting them by default would
 * turn "please check this" into "we checked this".
 */

const STATE_LABEL = {
  completed: "Completed",
  in_progress: "Taking now",
  planned: "Planned",
}

export default function IntakeView({ onOpenView }) {
  const [reading, setReading] = useState(null)
  const [selected, setSelected] = useState({})
  const [edits, setEdits] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const fileRef = useRef(null)

  async function upload(file) {
    if (!file) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const data = await api.readTranscript(file)
      setReading(data)
      // Pre-select only what the reader fully resolved. See the component note.
      const preselect = {}
      data.rows.forEach((row, i) => {
        if (row.status === "matched") preselect[i] = true
      })
      setSelected(preselect)
      setEdits({})
    } catch (err) {
      setError(err.message)
      setReading(null)
    } finally {
      setBusy(false)
    }
  }

  function rowValue(row, index, field) {
    return edits[index]?.[field] ?? row[field] ?? ""
  }

  function setRowValue(index, field, value) {
    setEdits((e) => ({ ...e, [index]: { ...e[index], [field]: value } }))
  }

  async function confirm() {
    const rows = reading.rows
      .map((row, i) => ({ row, i }))
      .filter(({ row, i }) => selected[i] && row.confirmable)
      .map(({ row, i }) => ({
        course_code: rowValue(row, i, "course_code"),
        state: rowValue(row, i, "state") || "completed",
        term: rowValue(row, i, "term") || null,
        grade: rowValue(row, i, "grade") || null,
      }))
    if (rows.length === 0) return

    setBusy(true)
    setError(null)
    try {
      setResult(await api.confirmTranscript(rows))
      setReading(null)
      setSelected({})
      setEdits({})
      if (fileRef.current) fileRef.current.value = ""
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const chosen = reading
    ? reading.rows.filter((row, i) => selected[i] && row.confirmable).length
    : 0

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Add your courses from a transcript</CardTitle>
          <CardDescription>
            Upload an unofficial transcript or advising record as a PDF and this will read
            the courses out of it, so you do not have to type them one at a time. Nothing is
            added to your record until you review it and confirm.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf,.pdf"
            disabled={busy}
            aria-label="Transcript PDF"
            onChange={(e) => upload(e.target.files?.[0])}
            className="rounded-md border bg-muted/40 p-2 text-sm"
          />
          <p className="text-xs text-muted-foreground">
            The file is read and discarded — it is never stored. A text PDF exported from
            Albert works; a photo or a scan has nothing to read.
          </p>
          {busy ? <p className="text-sm text-muted-foreground">Reading…</p> : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </CardContent>
      </Card>

      {result ? (
        <Card className="border-primary/40">
          <CardHeader>
            <CardTitle>
              Added {result.written} course{result.written === 1 ? "" : "s"} to your record
            </CardTitle>
            <CardDescription>
              They are stored as your own report of your record — the same as typing them in.
              Nothing here has been verified against Albert.
            </CardDescription>
          </CardHeader>
          <CardFooter className="flex-wrap gap-2">
            <Button size="sm" onClick={() => onOpenView?.("planner")}>
              See your degree check →
            </Button>
            <Button size="sm" variant="outline" onClick={() => onOpenView?.("chat")}>
              Ask what to do next →
            </Button>
          </CardFooter>
        </Card>
      ) : null}

      {reading?.no_text_layer ? (
        <Card>
          <CardHeader>
            <CardTitle>Nothing to read in that file</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {reading.notes.map((note, i) => (
              <p key={i} className="text-sm">
                {note}
              </p>
            ))}
          </CardContent>
          <CardFooter>
            <Button size="sm" variant="outline" onClick={() => onOpenView?.("planner")}>
              Enter courses by hand →
            </Button>
          </CardFooter>
        </Card>
      ) : null}

      {reading && !reading.no_text_layer ? (
        <Card>
          <CardHeader>
            <CardTitle>
              Read {reading.rows.filter((r) => r.course_code).length} course
              {reading.rows.filter((r) => r.course_code).length === 1 ? "" : "s"} from{" "}
              {reading.pages} page{reading.pages === 1 ? "" : "s"}
            </CardTitle>
            <CardDescription>
              {reading.counts.matched} ready · {reading.counts.needs_review} need a look ·{" "}
              {reading.counts.unreadable} could not be read
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {reading.notes.map((note, i) => (
              <p key={i} className="text-sm text-muted-foreground">
                {note}
              </p>
            ))}

            {reading.rows.map((row, i) => {
              if (!row.confirmable) {
                return (
                  <div key={i} className="rounded-md border border-dashed p-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">Could not read</Badge>
                      <span className="font-mono text-xs text-muted-foreground">
                        {row.raw}
                      </span>
                    </div>
                    {row.reasons.map((reason, j) => (
                      <p key={j} className="mt-1 text-sm text-muted-foreground">
                        {reason}
                      </p>
                    ))}
                  </div>
                )
              }

              const isMatched = row.status === "matched"
              return (
                <div
                  key={i}
                  className={`rounded-md border p-2 ${isMatched ? "" : "border-dashed bg-muted/30"}`}
                >
                  <label className="flex flex-wrap items-center gap-2">
                    <input
                      type="checkbox"
                      checked={!!selected[i]}
                      onChange={(e) =>
                        setSelected((s) => ({ ...s, [i]: e.target.checked }))
                      }
                      disabled={busy}
                    />
                    <span className="font-mono text-sm">{row.course_code}</span>
                    <Badge variant={isMatched ? "secondary" : "outline"}>
                      {isMatched ? "Ready" : "Needs a look"}
                    </Badge>
                  </label>

                  <div className="mt-2 flex flex-wrap items-center gap-2 pl-6">
                    <select
                      className="rounded-md border bg-background px-2 py-1 text-sm"
                      value={rowValue(row, i, "state") || "completed"}
                      onChange={(e) => setRowValue(i, "state", e.target.value)}
                      disabled={busy}
                      aria-label={`State for ${row.course_code}`}
                    >
                      {Object.entries(STATE_LABEL).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <input
                      className="w-28 rounded-md border bg-background px-2 py-1 text-sm"
                      value={rowValue(row, i, "term")}
                      onChange={(e) => setRowValue(i, "term", e.target.value)}
                      placeholder="Term"
                      disabled={busy}
                      aria-label={`Term for ${row.course_code}`}
                    />
                    <input
                      className="w-20 rounded-md border bg-background px-2 py-1 text-sm uppercase"
                      value={rowValue(row, i, "grade")}
                      onChange={(e) => setRowValue(i, "grade", e.target.value)}
                      placeholder="Grade"
                      disabled={busy}
                      aria-label={`Grade for ${row.course_code}`}
                    />
                  </div>

                  {row.reasons.map((reason, j) => (
                    <p key={j} className="mt-1 pl-6 text-sm text-muted-foreground">
                      {reason}
                    </p>
                  ))}
                </div>
              )
            })}
          </CardContent>
          <CardFooter className="flex-wrap gap-2">
            <Button disabled={busy || chosen === 0} onClick={confirm}>
              Add {chosen} course{chosen === 1 ? "" : "s"} to my record
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                const all = {}
                reading.rows.forEach((row, i) => {
                  if (row.confirmable) all[i] = true
                })
                setSelected(all)
              }}
            >
              Select all readable
            </Button>
            <p className="text-xs text-muted-foreground">
              Rows marked “needs a look” are not selected for you — that is the point of the
              label.
            </p>
          </CardFooter>
        </Card>
      ) : null}
    </div>
  )
}
