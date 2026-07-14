export function ContextPicker({
  facilityId,
  snapshotId,
}: {
  readonly facilityId?: string;
  readonly snapshotId?: string;
}) {
  return (
    <form action="/open-context" className="context-picker" method="get">
      <div className="context-field">
        <label htmlFor="facility-id">Facility ID</label>
        <input autoComplete="off" defaultValue={facilityId} id="facility-id" name="facility" placeholder="fac_…" />
      </div>
      <div className="context-field">
        <label htmlFor="snapshot-id">Immutable snapshot ID</label>
        <input autoComplete="off" defaultValue={snapshotId} id="snapshot-id" name="snapshot" placeholder="snp_… (optional)" />
      </div>
      <button className="context-submit" type="submit">Open context</button>
    </form>
  );
}
