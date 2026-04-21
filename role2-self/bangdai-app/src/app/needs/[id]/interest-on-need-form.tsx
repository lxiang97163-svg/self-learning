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
      data-testid="express-interest-need"
    >
      {pending ? "提交中…" : "表达兴趣"}
    </button>
  );
}

export function InterestOnNeedForm({
  needId,
  offerOptions,
}: {
  needId: string;
  offerOptions: { id: string; label: string }[];
}) {
  const [state, formAction] = useFormState(createInterestAction, initial);

  if (offerOptions.length === 0) {
    return <p className="text-sm text-slate-600">暂无匹配目的地的开放携带意向，请先发布携带意向。</p>;
  }

  return (
    <form action={formAction} className="space-y-2">
      <input type="hidden" name="needId" value={needId} />
      <div>
        <label className="text-sm text-slate-600">选择我的携带意向</label>
        <select
          name="offerId"
          required
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          data-testid="select-offer"
        >
          {offerOptions.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      {state?.error ? <p className="text-sm text-red-600">{state.error}</p> : null}
      <Submit />
    </form>
  );
}
