import { useEffect, useRef, useState } from "react"

/** The design's count-up: eased cubic, rAF-driven, fires when `trigger` flips true. */
export function useCountUp(target, duration = 800, trigger = true) {
  const [value, setValue] = useState(0)
  const raf = useRef(0)

  useEffect(() => {
    if (!trigger) return
    const start = performance.now()
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      setValue(Math.round(eased * target))
      if (t < 1) raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [target, duration, trigger])

  return value
}
