export default function Loading() {
  return <main aria-busy="true" aria-live="polite" className="loading-page"><span className="eyebrow">Loading governed workspace</span><h1>Retrieving authoritative state</h1><p>CanopyLedger will not infer values while snapshot outputs are loading.</p><div aria-hidden="true" className="loading-skeleton" /></main>;
}
