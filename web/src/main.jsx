import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Analytics } from '@vercel/analytics/react'
import { SpeedInsights } from '@vercel/speed-insights/react'
// The width axis, not just the weight axis: this product uses Archivo's widths to encode
// hierarchy (condensed labels, normal prose, expanded statements), so the `wdth` build is
// the one that matters. Self-hosted and split by unicode-range — Latin content fetches one
// ~35KB subset and nothing else.
import '@fontsource-variable/archivo/wdth.css'
import './index.css'
import './tailwind.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
    <Analytics />
    <SpeedInsights />
  </StrictMode>,
)
