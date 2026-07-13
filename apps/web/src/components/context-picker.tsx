"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { buildContextHref, parseContext } from "@/lib/context";

export function ContextPicker({
  facilityId,
  snapshotId,
}: {
  readonly facilityId?: string;
  readonly snapshotId?: string;
}) {
  const router = useRouter();
  const [facility, setFacility] = useState(facilityId ?? "");
  const [snapshot, setSnapshot] = useState(snapshotId ?? "");
  const [message, setMessage] = useState<string>();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const context = parseContext({ facility, snapshot });
    if (context.issue !== undefined) {
      setMessage(context.issue);
      return;
    }
    setMessage(undefined);
    router.push(buildContextHref(context));
  }

  return (
    <form className="context-picker" onSubmit={submit}>
      <div className="context-field">
        <label htmlFor="facility-id">Facility ID</label>
        <input
          autoComplete="off"
          id="facility-id"
          onChange={(event) => setFacility(event.target.value)}
          placeholder="fac_…"
          value={facility}
        />
      </div>
      <div className="context-field">
        <label htmlFor="snapshot-id">Immutable snapshot ID</label>
        <input
          autoComplete="off"
          id="snapshot-id"
          onChange={(event) => setSnapshot(event.target.value)}
          placeholder="snp_… (optional)"
          value={snapshot}
        />
      </div>
      <button className="context-submit" type="submit">
        Open context
      </button>
      <span aria-live="polite" className="sr-only">
        {message}
      </span>
    </form>
  );
}
