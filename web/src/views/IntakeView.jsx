import { useRef, useState } from "react"
import { AlertTriangle, Camera, CheckCircle, FileText, Info, Upload, XCircle } from "lucide-react"
import { api } from "@/api"
import { Button } from "@/components/ui/button"
import { MakeCard } from "@/components/make"
import { usePrefs } from "@/i18n"

/**
 * Transcript upload and review.
 *
 * The screen is arranged around one asymmetry: a row this tool reads *wrong* and the
 * student accepts puts coursework in their record they never took, and nothing
 * downstream will catch it — while a row it fails to read is merely missing, and
 * visible. So the review is per-row, opt-in, and everything uncertain is separated out
 * with its reason attached rather than mixed into a single "looks good" list.
 *
 * `matched` rows are pre-selected because the reader vouches for them entirely (code,
 * term, grade and state all resolved). `needs_review` rows are deliberately NOT
 * pre-selected: the whole point of that state is that a person has to look. Selecting
 * them by default would turn "please check this" into "we checked this".
 */

const STATE_LABEL = {
  completed: "Completed",
  in_progress: "Taking now",
  planned: "Planned",
}

export default function IntakeView({ onOpenView }) {
  const { t } = usePrefs()
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
      // Carries its own retry: the file is still in the input, so re-reading it is one
      // click. Without this a failed read is a dead end — the only way forward was to
      // notice the message and re-pick the same file from the OS dialog.
      //
      // Named, not captured. A stored callback would freeze the state it closed over,
      // which is harmless for a file but wrong for a confirm — see the confirm handler.
      setError({ message: err.message, retry: "upload", file })
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
      // The retry is a name, not this closure. `confirm` is re-created every render over
      // that render's `selected` and `edits`, so storing the function froze the selection
      // as it stood when the request failed: a student who then unticked a row or fixed a
      // grade and pressed "Try again" re-sent the old rows and the old grades, and the
      // success card confirmed a count they thought they had changed.
      setError({ message: err.message, retry: "confirm" })
    } finally {
      setBusy(false)
    }
  }

  function runRetry() {
    if (!error) return
    if (error.retry === "upload") upload(error.file)
    else if (error.retry === "confirm") confirm()
  }

  const chosen = reading
    ? reading.rows.filter((row, i) => selected[i] && row.confirmable).length
    : 0

  // Bulk selection is `matched` only, never `confirmable`. `confirmable` merely means the
  // row has a course code and is not unreadable, which is true of every `needs_review`
  // row — and `intake.service._as_reviewed` forces every OCR row to `needs_review`, so
  // keying the button on it would let one click stage a whole photographed transcript.
  // The server cannot catch that: POST /intake/confirm stamps `matched` on whatever it
  // receives, on the stated assumption that the student looked at each row. So the "no
  // OCR row is ever vouched for" rule has to hold here, in the only place that could
  // break it. Same predicate as the post-upload pre-select above, deliberately.
  const readyCount = reading ? reading.rows.filter((row) => row.status === "matched").length : 0

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      {/* Header — the design's transcript header: icon, title, live stat trio. */}
      <div className="pp-slide-down flex items-center gap-4">
        <FileText size={16} style={{ color: "var(--color-violet-light)" }} aria-hidden="true" />
        <div className="flex-1">
          <div className="text-[14px] font-semibold" style={{ color: "var(--color-ink)" }}>
            {t("nav.intake")}
          </div>
          <div className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
            Upload once, review each row, confirm what is right.
          </div>
        </div>
        {reading && !reading.no_text_layer ? (
          <div className="flex items-center gap-4">
            {[
              { label: "ready", count: reading.counts.matched, color: "var(--color-emerald)" },
              { label: "review", count: reading.counts.needs_review, color: "var(--color-amber)" },
              { label: "unreadable", count: reading.counts.unreadable, color: "var(--color-rose)" },
            ].map((s) => (
              <div key={s.label} className="text-center">
                <div className="text-[17px] leading-none font-bold" style={{ color: s.color }}>{s.count}</div>
                <div className="mt-0.5 text-[10px]" style={{ color: "var(--color-ink-3)" }}>{s.label}</div>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      {/* The design's photo-warning card — this product's real privacy disclosure,
          said before the upload because only the student can decide. */}
      <div
        className="pp-slide-up flex items-start gap-2.5 rounded-xl px-4 py-3"
        style={{ background: "var(--color-rose-muted)", border: "1px solid rgba(190,18,60,0.2)" }}
      >
        <Camera size={13} style={{ color: "var(--color-rose)", flexShrink: 0, marginTop: 1 }} aria-hidden="true" />
        <div>
          <div className="text-[12px] font-semibold" style={{ color: "var(--color-rose)" }}>
            If you upload a photo or a scan
          </div>
          <div className="mt-0.5 text-[11px] leading-relaxed" style={{ color: "var(--color-rose)", opacity: 0.75 }}>
            The image is sent to OpenAI's vision service to be read — there is no text in it
            to extract. It is not stored there or here. Reading characters from an image is
            imperfect, so every row from an image has to be checked by you individually, and
            none can be added in bulk.
          </div>
        </div>
      </div>
      <div
        className="pp-slide-up flex items-start gap-2.5 rounded-xl px-4 py-2.5"
        style={{ background: "var(--color-sky-muted)", border: "1px solid rgba(96,165,250,0.2)", animationDelay: "60ms" }}
      >
        <Info size={12} style={{ color: "var(--color-sky)", flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
        <p className="text-[11px] leading-relaxed" style={{ color: "var(--color-sky)", opacity: 0.85 }}>
          The file is read and discarded — never stored. Courses enter your record as your
          own report, the same as typing them. A text PDF exported from Albert is the most
          accurate option by some distance.
        </p>
      </div>

      <MakeCard delay={120}>
        <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
          <Upload size={13} aria-hidden="true" style={{ color: "var(--color-ink-3)" }} />
          Add your courses from a transcript
        </div>
        <div className="flex flex-col gap-2">
          {/* The design's upload button, fronting the real file input. */}
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf,.pdf,image/jpeg,image/png,image/webp,image/heic,.jpg,.jpeg,.png,.heic"
            disabled={busy}
            aria-label="Transcript PDF or photo"
            onChange={(e) => upload(e.target.files?.[0])}
            className="sr-only"
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            className="flex w-fit items-center gap-2 rounded-xl px-3 py-2 text-[12px] font-medium"
            style={{
              background: "var(--color-surface-2)",
              color: "var(--color-ink-2)",
              border: "1px solid var(--color-rail-strong)",
            }}
          >
            <Upload size={12} aria-hidden="true" />
            Choose a PDF or photo…
          </button>
          {/* Both states are announced. Reading a photo goes to a vision endpoint and can
              take many seconds, and the failure was previously a bare <p> — a screen-reader
              user got silence in both directions, on the one screen where the wait is long
              enough to make you wonder whether the click registered. */}
          {busy ? (
            <p className="text-sm text-muted-foreground" role="status">
              Reading…
            </p>
          ) : null}
          {error ? (
            <div
              className="flex flex-wrap items-center gap-2 text-sm text-destructive"
              role="alert"
            >
              <span>{error.message}</span>
              {error.retry ? (
                <Button variant="outline" size="sm" disabled={busy} onClick={runRetry}>
                  Try again
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
      </MakeCard>

      {result ? (
        <MakeCard style={{ borderColor: "rgba(124,58,237,0.4)" }}>
          <div className="flex items-center gap-2 text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
            <CheckCircle size={13} style={{ color: "var(--color-emerald)" }} aria-hidden="true" />
            Added {result.written} course{result.written === 1 ? "" : "s"} to your record
          </div>
          <p className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-3)" }}>
            They are stored as your own report of your record — the same as typing them in.
            Nothing here has been verified against Albert.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => onOpenView?.("planner")}>
              See your degree check →
            </Button>
            <Button size="sm" variant="outline" onClick={() => onOpenView?.("chat")}>
              Ask what to do next →
            </Button>
          </div>
        </MakeCard>
      ) : null}

      {reading?.no_text_layer ? (
        <MakeCard>
          <div className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
            Nothing to read in that file
          </div>
          <div className="mt-2 flex flex-col gap-2">
            {reading.notes.map((note, i) => (
              <p key={i} className="text-[12px]" style={{ color: "var(--color-ink-2)" }}>
                {note}
              </p>
            ))}
          </div>
          <div className="mt-3">
            <Button size="sm" variant="outline" onClick={() => onOpenView?.("planner")}>
              Enter courses by hand →
            </Button>
          </div>
        </MakeCard>
      ) : null}

      {reading && !reading.no_text_layer ? (
        <MakeCard delay={60}>
          <div className="text-[13px] font-semibold" style={{ color: "var(--color-ink)" }}>
            Read {reading.rows.filter((r) => r.course_code).length} course
            {reading.rows.filter((r) => r.course_code).length === 1 ? "" : "s"} from{" "}
            {reading.pages} page{reading.pages === 1 ? "" : "s"}
          </div>
          <div className="mt-3 flex flex-col gap-3">
            {/* An image reading is a different kind of result and should not look like a
                clean one. Everything below is a guess at characters, so the screen says so
                once at the top rather than relying on the student noticing that every row
                happens to be flagged. */}
            {reading.read_by_ocr ? (
              <div
                className="flex items-start gap-2 rounded-xl px-3 py-2.5"
                style={{ background: "var(--color-amber-muted)", border: "1px solid rgba(180,83,9,0.2)" }}
              >
                <AlertTriangle size={11} style={{ color: "var(--color-amber)", flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
                <p className="text-[11px] leading-relaxed" style={{ color: "var(--color-amber)" }}>
                  <strong>Read from an image.</strong> These course codes and grades were
                  recognised from a picture, not extracted from text, so each one is a best
                  guess — check it against your transcript before adding it. Nothing here can
                  be added in bulk. A text PDF exported from Albert avoids all of this.
                </p>
              </div>
            ) : null}

            {reading.notes.map((note, i) => (
              <p key={i} className="text-sm text-muted-foreground">
                {note}
              </p>
            ))}

            {reading.rows.map((row, i) => {
              if (!row.confirmable) {
                return (
                  <div
                    key={i}
                    className="rounded-xl p-3"
                    style={{ background: "var(--color-rose-muted)", border: "1px dashed rgba(190,18,60,0.25)" }}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <XCircle size={12} style={{ color: "var(--color-rose)" }} aria-hidden="true" />
                      <span className="text-[10px] font-semibold tracking-wide uppercase" style={{ color: "var(--color-rose)" }}>
                        Could not read
                      </span>
                      <span className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: "var(--color-ink-3)" }}>
                        {row.raw}
                      </span>
                    </div>
                    {row.reasons.map((reason, j) => (
                      <p key={j} className="mt-1 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
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
                  className="pp-slide-up rounded-xl p-3"
                  style={{
                    background: isMatched ? "var(--color-surface-2)" : "var(--color-amber-muted)",
                    border: `1px solid ${isMatched ? "var(--color-rail)" : "rgba(180,83,9,0.2)"}`,
                    animationDelay: `${i * 40}ms`,
                  }}
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
                    <span className="text-[11px] font-medium" style={{ fontFamily: "var(--font-mono)", color: "var(--color-violet-light)" }}>
                      {row.course_code}
                    </span>
                    <span
                      className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium"
                      style={
                        isMatched
                          ? { background: "var(--color-emerald-muted)", color: "var(--color-emerald)" }
                          : { background: "var(--color-amber-muted)", color: "var(--color-amber)" }
                      }
                    >
                      {isMatched ? <CheckCircle size={10} aria-hidden="true" /> : <AlertTriangle size={10} aria-hidden="true" />}
                      {isMatched ? "Ready" : "Needs a look"}
                    </span>
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
                    <p key={j} className="mt-1 pl-6 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
                      {reason}
                    </p>
                  ))}
                </div>
              )
            })}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button disabled={busy || chosen === 0} onClick={confirm}>
              Add {chosen} course{chosen === 1 ? "" : "s"} to my record
            </Button>
            <Button
              variant="outline"
              disabled={busy || readyCount === 0}
              onClick={() => {
                const all = {}
                reading.rows.forEach((row, i) => {
                  if (row.status === "matched") all[i] = true
                })
                setSelected(all)
              }}
            >
              Select all {readyCount} ready
            </Button>
            <p className="text-[11px]" style={{ color: "var(--color-ink-3)" }}>
              Rows marked “needs a look” are not selected for you, and cannot be selected in
              bulk — that is the point of the label.
            </p>
          </div>
        </MakeCard>
      ) : null}
    </div>
  )
}
