"use client";

export default function GlobalError({ reset }: { readonly error: Error & { digest?: string }; readonly reset: () => void }) {
  return (
    <html lang="en">
      <body className="error-page">
        <main className="unavailable-panel panel" role="alert">
          <span className="eyebrow">Unexpected state</span>
          <h1>The workspace could not be rendered</h1>
          <p>No authoritative calculation is displayed. Retry after the service is available.</p>
          <button className="context-submit" onClick={reset} type="button">Retry</button>
        </main>
      </body>
    </html>
  );
}
