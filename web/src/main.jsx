import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Analytics } from '@vercel/analytics/react'
import { SpeedInsights } from '@vercel/speed-insights/react'
// The Figma Make design's three faces, self-hosted: Fraunces (display serif), DM Sans
// (text), JetBrains Mono (code and figures). Archivo stays installed for the not-yet-
// rebuilt views that still ask for its width axis via the legacy --font-ui alias — which
// now points at DM Sans, so those views degrade to the new family rather than breaking.
import '@fontsource-variable/fraunces/index.css'
import '@fontsource-variable/dm-sans/index.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import './index.css'
import './tailwind.css'
import App from './App.jsx'
import { PrefsProvider } from './i18n'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <PrefsProvider>
      <App />
    </PrefsProvider>
    <Analytics />
    <SpeedInsights />
  </StrictMode>,
)
