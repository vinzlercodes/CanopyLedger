import { headers } from "next/headers";

import type { FacilityResponse, SnapshotManifestResponse } from "../../../../../typescript/generated/index";

import { ApiProblem, createApiClient, requireSuccess } from "@/lib/api/client";

export type LoadedContext =
  | { readonly kind: "empty" }
  | {
      readonly kind: "working";
      readonly facility: FacilityResponse;
    }
  | {
      readonly kind: "snapshot";
      readonly facility: FacilityResponse;
      readonly snapshot: SnapshotManifestResponse;
    }
  | {
      readonly kind: "unavailable";
      readonly title: string;
      readonly detail: string;
      readonly status: "unauthorized" | "not-found" | "failed" | "invalid";
    };

export async function loadContext({
  facilityId,
  snapshotId,
}: {
  readonly facilityId?: string;
  readonly snapshotId?: string;
}): Promise<LoadedContext> {
  if (facilityId === undefined) {
    return { kind: "empty" };
  }

  try {
    const requestHeaders = await headers();
    const client = createApiClient(requestHeaders.get("authorization"));
    const facility = requireSuccess(await client.getFacility(facilityId));

    if (snapshotId === undefined) {
      return { kind: "working", facility };
    }

    const snapshot = requireSuccess(await client.getSnapshotManifest(snapshotId));
    if (snapshot.facility_id !== facility.id) {
      return {
        kind: "unavailable",
        status: "invalid",
        title: "Snapshot context is inconsistent",
        detail: "The selected immutable snapshot belongs to a different facility. Select a snapshot from this facility instead.",
      };
    }

    return { kind: "snapshot", facility, snapshot };
  } catch (error) {
    if (error instanceof ApiProblem) {
      if (error.status === 401 || error.status === 403) {
        return {
          kind: "unavailable",
          status: "unauthorized",
          title: "Authentication or role access is required",
          detail: "Sign in with a principal permitted to view this facility. The application does not disclose whether an unavailable resource exists.",
        };
      }
      if (error.status === 404) {
        return {
          kind: "unavailable",
          status: "not-found",
          title: "This resource is unavailable",
          detail: "The facility or snapshot is either absent or not visible to your current role.",
        };
      }
    }

    return {
      kind: "unavailable",
      status: "failed",
      title: "CanopyLedger could not load this context",
      detail: "Check the API connection and try again. No calculation values are shown while authoritative state is unavailable.",
    };
  }
}
