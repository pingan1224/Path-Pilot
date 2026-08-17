import { useEffect, useRef, useState } from "react"

/** The design's count-up: eased cubic, rAF-driven, fires when `trigger` flips true.
 *
 *  Steps in whole numbers for a whole-number target and in tenths otherwise. The rounding
 *  used to be unconditional, which meant a 1.5-credit total — three encoded degrees are
 *  built out of 1.5-credit courses — animated up and landed on `2`. A progress ring that
 *  reads one credit high is worse than no ring: it is wrong in the direction that tells a
 *  student they are further along than they are.
 */
export function useCountUp(target, duration = 800, trigger = true) {
  const [value, setValue] = useState(0)
  const raf = useRef(0)

  useEffect(() => {
    if (!trigger) return
    const start = performance.now()
    const step = Number.isInteger(target) ? 1 : 10
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      setValue(Math.round(eased * target * step) / step)
      if (t < 1) raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [target, duration, trigger])

  return value
}
