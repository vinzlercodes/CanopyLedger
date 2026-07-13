import Link from "next/link";

export default function NotFound() {
  return (
    <main className="error-page">
      <section className="unavailable-panel panel">
        <span className="eyebrow">Unavailable</span>
        <h1>This workspace route does not exist</h1>
        <p>Open a permitted facility and immutable snapshot context from the application shell.</p>
        <Link className="secondary-action" href="/">Return to context selection</Link>
      </section>
    </main>
  );
}
