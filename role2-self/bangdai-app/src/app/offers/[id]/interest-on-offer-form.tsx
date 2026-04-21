"use client";

import { createInterestAction } from "@/actions/match";
import { useFormState, useFormStatus } from "react-dom";

const initial = { error: "" as string };

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-60"
      data-testid="express-interest"
    >
      {pending ? "提交中…" : "表达兴趣"}
    </button>
  );
}

export function InterestOnOfferForm({
  offerId,
  needOptions,
}: {
  offerId: string;
  needOptions: { id: string; label: string }[];
}) {
  const [state, formAction] = useFormState(createInterestAction, initial);

  if (needOptions.length === 0) {
    return <p className="text-sm text-slate-600">暂无匹配目的地的开放需求，请先发布宠物帮带需求。</p>;
  }

  return (
    <form action={formAction} className="space-y-2">
      <input type="hidden" name="offerId" value={offerId} />
      <div>
        <label className="text-sm text-slate-600">选择我的需求</label>
        <select
          name="needId"
          required
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          data-testid="select-need"
        >
          {needOptions.map((n) => (
            <option key={n.id} value={n.id}>
              {n.label}
            </option>
          ))}
        </select>
      </div>
      {state?.error ? <p className="text-sm text-red-600">{state.error}</p> : null}
      <Submit />
    </form>
  );
}
