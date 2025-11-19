declare module 'react-error-boundary' {
    import * as React from 'react';
    export interface FallbackProps { error: Error; resetErrorBoundary: () => void }
    export interface ErrorBoundaryProps { fallback?: React.ReactNode; FallbackComponent?: React.ComponentType<FallbackProps>; onError?: (error: Error, info: { componentStack: string }) => void; onReset?: () => void; children?: React.ReactNode }
    export class ErrorBoundary extends React.Component<ErrorBoundaryProps, { hasError: boolean }> { }
}
