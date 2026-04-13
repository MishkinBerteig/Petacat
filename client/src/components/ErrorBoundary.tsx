// ---------------------------------------------------------------------------
// ErrorBoundary -- Catches rendering errors per-panel
// ---------------------------------------------------------------------------
//
// Wraps individual panels so that a crash in one component does not take down
// the entire application.  Displays a compact error message with a Retry
// button that resets the boundary and re-renders the children.
// ---------------------------------------------------------------------------

import { Component, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Label shown in the fallback UI so the user knows which panel failed. */
  fallback?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Log to the console so developers can inspect the full stack trace.
    console.error(
      `[ErrorBoundary] ${this.props.fallback ?? 'Panel'} crashed:`,
      error,
      info.componentStack,
    );
  }

  private handleRetry = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      const label = this.props.fallback ?? 'This panel';
      return (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            padding: 16,
            height: '100%',
            color: 'var(--text-secondary)',
            fontSize: 13,
            textAlign: 'center',
          }}
        >
          <div style={{ color: '#e06c75', fontWeight: 600 }}>
            {label} encountered an error
          </div>
          {this.state.error && (
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                maxWidth: '100%',
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                color: 'var(--text-muted, #888)',
                maxHeight: 80,
              }}
            >
              {this.state.error.message}
            </div>
          )}
          <button
            onClick={this.handleRetry}
            style={{
              marginTop: 4,
              padding: '4px 12px',
              fontSize: 12,
              cursor: 'pointer',
              background: 'var(--bg-card, #2c2c2c)',
              color: 'var(--text-accent, #61afef)',
              border: '1px solid var(--border, #444)',
              borderRadius: 4,
            }}
          >
            Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
