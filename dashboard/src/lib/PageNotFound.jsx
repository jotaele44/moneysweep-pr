import { useLocation } from 'react-router-dom'

// Auth-stripped 404 (no base44 auth lookup).
export default function PageNotFound() {
  const location = useLocation()
  const pageName = location.pathname.substring(1)

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-slate-950 text-slate-200">
      <div className="max-w-md w-full text-center space-y-6">
        <div className="space-y-2">
          <h1 className="text-7xl font-light text-slate-700">404</h1>
          <div className="h-0.5 w-16 bg-slate-800 mx-auto"></div>
        </div>
        <div className="space-y-3">
          <h2 className="text-2xl font-medium text-slate-100">Page Not Found</h2>
          <p className="text-slate-400 leading-relaxed">
            The page <span className="font-medium text-slate-300">"{pageName}"</span> could not be found.
          </p>
        </div>
        <div className="pt-2">
          <button
            onClick={() => (window.location.href = '/')}
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-slate-200 bg-slate-900 border border-slate-700 rounded-lg hover:bg-slate-800 transition-colors"
          >
            Go Home
          </button>
        </div>
      </div>
    </div>
  )
}
