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
import { ErrorBoundary } from './components/ErrorBoundary'
import { PrefsProvider } from './i18n'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {/* The shell has its own boundaries around the panes, which are the ones a student
        should ever meet. This is the backstop for a throw in the shell itself — without
        it that case is still a blank page.

        It wraps the provider rather than sitting inside it, because a boundary cannot
        catch a throw from its own ancestor. PrefsProvider reads localStorage as it
        initialises, and that access throws outright where site data is blocked, so with
        the old nesting the very failure this boundary exists to prevent was the one it
        could not see. The boundary is deliberately context-free — its copy is hardcoded
        English — so it does not need the provider it now encloses. */}
    <ErrorBoundary>
      <PrefsProvider>
        <App />
      </PrefsProvider>
    </ErrorBoundary>
    <Analytics />
    <SpeedInsights />
  </StrictMode>,
)
