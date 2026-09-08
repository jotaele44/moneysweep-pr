import { Component } from 'react'

// Last-resort guard: a render crash shows a readable panel instead of a blank page.
// Reload clears module-level query caches as well as the failed component tree.
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-3 bg-background p-8 text-center text-foreground">
          <h1 className="text-lg font-semibold">Something went wrong</h1>
          <p className="max-w-md text-sm text-muted-foreground">{String(this.state.error?.message || this.state.error)}</p>
          <button
            className="glow-border rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
            onClick={() => window.location.reload()}
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
