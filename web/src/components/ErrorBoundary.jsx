import { Component } from "react"
import { AlertTriangle } from "lucide-react"

/**
 * The last honest surface.
 *
 * React unmounts the whole tree when a render throws and nothing catches it, which
 * leaves the ground colour and nothing else — no message, no way back, and Back and
 * Forward do nothing because the URL is fine and there is no longer a component
 * listening to it. Only a refresh recovers. A student who hit that would have no idea
 * whether their upload had been written or lost.
 *
 * That is the silent failure rule 6 forbids, one layer below where the rule is usually
 * applied: every dependency has a visible degradation path, and the renderer is a
 * dependency too. So a crash now says what broke, offers the way back, and — the part
 * that matters for a records product — states what it does and does not imply about the
 * student's data.
 *
 * `resetKey` clears the error when the view changes, so leaving a broken screen is
 * enough to recover; without it the boundary would latch and the shell would stay dead
 * after the student navigated away from the failure.
 */
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidUpdate(prev) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null })
    }
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="flex h-full items-start justify-center overflow-auto p-6">
        <div
          className="pp-slide-up w-full max-w-lg rounded-2xl p-5"
          style={{
            background: "var(--color-surface)",
            border: "1px solid rgba(190,18,60,0.25)",
          }}
          role="alert"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle size={15} style={{ color: "var(--color-rose)" }} aria-hidden="true" />
            <span className="text-[14px] font-semibold" style={{ color: "var(--color-ink)" }}>
              This screen stopped working
            </span>
          </div>

          <p className="mt-2 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-2)" }}>
            Something in the page failed while drawing it. This is a fault in Path Pilot,
            not in what you entered.
          </p>
          {/* The question a student actually has at this moment. The app never writes as
              a side effect of rendering, so this is a statement of fact, not a hedge. */}
          <p className="mt-2 text-[12px] leading-relaxed" style={{ color: "var(--color-ink-2)" }}>
            Nothing was saved or changed by this failure — your record is whatever it was
            before you opened this screen. Anything you had confirmed earlier is still
            there.
          </p>

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="rounded-xl px-3 py-2 text-[12px] font-medium"
              style={{ background: "var(--color-violet)", color: "#fff" }}
            >
              Try this screen again
            </button>
            <button
              type="button"
              onClick={() => {
                window.history.pushState(null, "", "/")
                window.dispatchEvent(new PopStateEvent("popstate"))
                this.setState({ error: null })
              }}
              className="rounded-xl px-3 py-2 text-[12px] font-medium"
              style={{
                background: "var(--color-surface-2)",
                color: "var(--color-ink-2)",
                border: "1px solid var(--color-rail-strong)",
              }}
            >
              Back to the assistant
            </button>
          </div>

          <details className="mt-3 text-[11px]" style={{ color: "var(--color-ink-3)" }}>
            <summary className="cursor-pointer">Technical detail</summary>
            <pre
              className="nx-scroll mt-1 overflow-auto rounded-lg p-2"
              style={{
                background: "var(--color-code-bg)",
                fontFamily: "var(--font-mono)",
                maxHeight: 160,
              }}
            >
              {String(this.state.error?.stack ?? this.state.error)}
            </pre>
          </details>
        </div>
      </div>
    )
  }
}
