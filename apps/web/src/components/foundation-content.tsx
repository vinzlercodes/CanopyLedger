import { AuthorityBadge } from "@/components/authority-badge";
import { Icon } from "@/components/icon";
import type { LoadedContext } from "@/lib/api/load-context";

function GovernanceKey() {
  const items = [
    ["working", "Editable facility data; it has not become authoritative output."],
    ["frozen", "Bundle-pinned immutable input. It can be inspected but not changed."],
    ["published", "Successful deterministic stage output, retained with its digest."],
    ["recommendation", "Advisory result. It is never a human decision."],
    ["final", "A recorded decision made by an authorized, independent person."],
  ] as const;

  return (
    <section aria-labelledby="governance-key-title" className="governance-key panel">
      <div className="panel-heading">
        <span className="eyebrow">Reading this workspace</span>
        <h2 id="governance-key-title">Governance workflow key</h2>
      </div>
      <ul>
        {items.map(([kind, description]) => (
          <li key={kind}>
            <AuthorityBadge kind={kind} />
            <span>{description}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function EmptyContext() {
  return (
    <div className="foundation-grid">
      <section className="hero-panel panel">
        <div className="empty-symbol" aria-hidden="true"><Icon name="search" /></div>
        <span className="eyebrow">Facility workspace</span>
        <h1>Select a facility to establish context</h1>
        <p>
          Enter a permitted facility ID above. Add an immutable snapshot ID when reviewing frozen inputs or published outputs.
        </p>
        <div className="instruction-row">
          <span><Icon name="lock" /> Browser code never calculates CBB, IRC, hedge, scenario, or decision values.</span>
          <span><Icon name="shield" /> Human approval remains visible and separate from recommendations.</span>
        </div>
      </section>
      <GovernanceKey />
      <section className="foundation-card panel">
        <Icon name="lock" />
        <h2>Immutable snapshots</h2>
        <p>Each snapshot pins its market, policy, legal-interpretation, and computation bundles.</p>
      </section>
      <section className="foundation-card panel">
        <Icon name="shield" />
        <h2>Human approval required</h2>
        <p>Recommendations are advisory. Final decisions require an authorized independent approver.</p>
      </section>
      <section className="foundation-card panel">
        <Icon name="document" />
        <h2>Lineage stays attached</h2>
        <p>Source IDs, digests, timestamps, stage state, and reason codes stay with authoritative values.</p>
      </section>
    </div>
  );
}

function UnavailableContext({ context }: { readonly context: Extract<LoadedContext, { readonly kind: "unavailable" }> }) {
  return (
    <section className="unavailable-panel panel" role="alert">
      <div className="unavailable-icon"><Icon name={context.status === "failed" ? "warning" : "lock"} /></div>
      <span className="eyebrow">{context.status.replace("-", " ")}</span>
      <h1>{context.title}</h1>
      <p>{context.detail}</p>
      <a className="secondary-action" href="/">Return to context selection</a>
    </section>
  );
}

function WorkingContext({ context }: { readonly context: Extract<LoadedContext, { readonly kind: "working" }> }) {
  return (
    <div className="context-page">
      <section className="context-overview panel">
        <div>
          <span className="eyebrow">Mutable facility context</span>
          <h1>{context.facility.legal_name}</h1>
          <p>Working draft data may change. It is not a frozen snapshot or published analytical output.</p>
        </div>
        <AuthorityBadge kind="working" />
      </section>
      <section className="metadata-grid">
        <article className="metadata-card panel"><span>Facility ID</span><code>{context.facility.id}</code></article>
        <article className="metadata-card panel"><span>Working version</span><strong>v{context.facility.version}</strong><small>Strong ETag required for mutations</small></article>
        <article className="metadata-card panel"><span>Facility currency</span><strong>{context.facility.currency}</strong><small>Amounts are not displayed until an authoritative output is retrieved.</small></article>
      </section>
      <section className="notice-panel panel">
        <Icon name="spark" />
        <div><h2>Next governed step</h2><p>Use an immutable snapshot ID when it is available. Snapshot history and facility-list projections are intentionally deferred to the backend read-model milestone.</p></div>
      </section>
    </div>
  );
}

function SnapshotContext({ context }: { readonly context: Extract<LoadedContext, { readonly kind: "snapshot" }> }) {
  const bundles = [
    ["Market", context.snapshot.market_bundle],
    ["Policy", context.snapshot.policy_bundle],
    ["Legal interpretation", context.snapshot.legal_interpretation_bundle],
    ["Computation", context.snapshot.computation_bundle],
  ] as const;
  return (
    <div className="context-page">
      <section className="context-overview panel">
        <div>
          <span className="eyebrow">Immutable facility context</span>
          <h1>{context.facility.legal_name}</h1>
          <p>Frozen input state only. Published stage outputs and decisions must be retrieved separately and are never recalculated here.</p>
        </div>
        <AuthorityBadge kind="frozen" />
      </section>
      <section className="metadata-grid">
        <article className="metadata-card panel"><span>Snapshot ID</span><code>{context.snapshot.snapshot_id}</code></article>
        <article className="metadata-card panel"><span>As of</span><strong>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date(context.snapshot.as_of))} UTC</strong><small>Source timestamp: {context.snapshot.as_of}</small></article>
        <article className="metadata-card panel"><span>Manifest digest</span><code>{context.snapshot.digest}</code></article>
      </section>
      <section className="bundle-panel panel" aria-labelledby="bundle-title">
        <div className="panel-heading"><span className="eyebrow">Pinned at freeze</span><h2 id="bundle-title">Bundle lineage</h2></div>
        <div className="bundle-list">
          {bundles.map(([label, bundle]) => (
            <article key={label}>
              <span>{label} bundle</span>
              <code>{bundle.resource_id}</code>
              <small>{bundle.digest}</small>
            </article>
          ))}
        </div>
      </section>
      <section className="notice-panel panel">
        <Icon name="document" />
        <div><h2>Stage and decision data are intentionally absent</h2><p>Foundation scope establishes snapshot lineage only. Future read models will render published outputs with stage, digest, timestamp, reason-code, and approval-state context.</p></div>
      </section>
    </div>
  );
}

export function FoundationContent({ context }: { readonly context: LoadedContext }) {
  if (context.kind === "empty") return <EmptyContext />;
  if (context.kind === "unavailable") return <UnavailableContext context={context} />;
  if (context.kind === "working") return <WorkingContext context={context} />;
  return <SnapshotContext context={context} />;
}
