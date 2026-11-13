import React from 'react'
import ReactDOM from 'react-dom/client'
// Self-hosted fonts (bundled) replace the render-blocking Google Fonts @import —
// no external request, so the offline single-file export stays self-contained.
import '@fontsource-variable/inter'
import '@fontsource/jetbrains-mono'
import App from '@/App.jsx'
import ErrorBoundary from '@/components/ErrorBoundary'
import '@/index.css'
import '@pr-federation/react/styles.css'
import '@/styles/pilot.css'

// This app commits to its dark cyan console identity. Stamp the shared
// federation.css signals so accent + dark tokens apply across the federation.
document.documentElement.dataset.repo = 'moneysweep-pr'
document.documentElement.dataset.theme = 'dark'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)

// Archive design is isolated from the existing backend and semantic tokens.
import "./zip-design/tokens.css";
import "./zip-design/adaptation.css";
