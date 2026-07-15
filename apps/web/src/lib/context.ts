export type FacilitySnapshotContext = {
  readonly facilityId?: string;
  readonly snapshotId?: string;
  readonly issue?: string;
};

export function parseContext(values: {
  readonly facility?: string;
  readonly snapshot?: string;
}): FacilitySnapshotContext {
  const facilityId = values.facility?.trim() || undefined;
  const snapshotId = values.snapshot?.trim() || undefined;

  if (snapshotId !== undefined && facilityId === undefined) {
    return {
      facilityId: undefined,
      snapshotId: undefined,
      issue: "A facility must be selected before an immutable snapshot can be opened.",
    };
  }

  return { facilityId, snapshotId };
}

export function buildContextHref({ facilityId, snapshotId }: FacilitySnapshotContext): string {
  if (facilityId === undefined) {
    return "/";
  }

  const encodedFacilityId = encodeURIComponent(facilityId);
  if (snapshotId === undefined) {
    return `/facilities/${encodedFacilityId}/cockpit`;
  }

  return `/facilities/${encodedFacilityId}/snapshots/${encodeURIComponent(snapshotId)}/cockpit`;
}

export type WorkspaceSlug = "cockpit" | "collateral" | "evidence" | "risk/hedge" | "risk/scenarios" | "climate" | "credit" | "approvals";

export function buildWorkspaceHref(
  { facilityId, snapshotId }: FacilitySnapshotContext,
  workspace: WorkspaceSlug,
): string {
  if (facilityId === undefined || snapshotId === undefined) {
    return buildContextHref({ facilityId, snapshotId });
  }
  return `/facilities/${encodeURIComponent(facilityId)}/snapshots/${encodeURIComponent(snapshotId)}/${workspace}`;
}
