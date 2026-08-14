import { usePrefs } from "@/i18n"

/**
 * The design's ambient background: two blurred violet/blue blobs drifting on 22s/18s
 * loops behind everything, dark theme only. Ported verbatim on the 1:1 branch — this is
 * the piece the adapted skin refused as meaningless motion, and the refusal was
 * overridden by the owner's ask for the design exactly as drawn. The global
 * prefers-reduced-motion rule still freezes both blobs.
 */
export default function AmbientBg() {
  const { theme } = usePrefs()
  if (theme !== "dark") return null

  return (
    <div className="pointer-events-none fixed inset-0 overflow-hidden" style={{ zIndex: 0 }}>
      <div
        style={{
          position: "absolute",
          width: 700,
          height: 700,
          borderRadius: "50%",
          top: "-15%",
          left: "-8%",
          background: "radial-gradient(ellipse, rgba(109,40,217,0.10) 0%, transparent 70%)",
          filter: "blur(40px)",
          animation: "pp-blob-1 22s ease-in-out infinite",
          willChange: "transform",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 600,
          height: 600,
          borderRadius: "50%",
          bottom: "-10%",
          right: "-5%",
          background: "radial-gradient(ellipse, rgba(59,130,246,0.07) 0%, transparent 70%)",
          filter: "blur(40px)",
          animation: "pp-blob-2 18s ease-in-out infinite",
          willChange: "transform",
        }}
      />
    </div>
  )
}
