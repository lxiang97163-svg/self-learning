"use client";

import { acceptInterestAction, rejectInterestAction } from "@/actions/match";
import { useFormState, useFormStatus } from "react-dom";

const initial = { error: "" as string };

function Submit({ label }: { label: string }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-60"
    >
      {pending ? "…" : label}
    </button>
  );
}

export function MatchActions({ matchId }: { matchId: string }) {
  const [acceptState, acceptAction] = useFormState(acceptInterestAction, initial);
  const [rejectState, rejectAction] = useFormState(rejectInterestAction, initial);

  return (
    <div className="flex flex-wrap gap-3">
      <form action={acceptAction}>
        <input type="hidden" name="matchId" value={matchId} />
        <Submit label="接受" />
      </form>
      <form action={rejectAction}>
        <input type="hidden" name="matchId" value={matchId} />
        <Submit label="拒绝" />
      </form>
      {(acceptState?.error || rejectState?.error) && (
        <p className="w-full text-sm text-red-600">{acceptState.error || rejectState.error}</p>
      )}
    </div>
  );
}
