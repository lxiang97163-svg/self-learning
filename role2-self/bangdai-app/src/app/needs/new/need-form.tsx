"use client";

import { createPetCarryNeedAction } from "@/actions/need";
import { useFormState, useFormStatus } from "react-dom";

const initial = { error: "" as string };

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
      data-testid="need-submit"
    >
      {pending ? "提交中…" : "发布需求"}
    </button>
  );
}

export function NeedForm() {
  const [state, formAction] = useFormState(createPetCarryNeedAction, initial);

  return (
    <form action={formAction} className="space-y-4">
      <div>
        <label className="text-sm text-slate-600">出发地（可选）</label>
        <input
          name="originCity"
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          placeholder="宠物当前所在城市"
        />
      </div>
      <div>
        <label className="text-sm text-slate-600">目的地城市</label>
        <input
          name="destinationCity"
          required
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          data-testid="need-dest"
        />
      </div>
      <div>
        <label className="text-sm text-slate-600">希望到达日期</label>
        <input
          name="neededByDate"
          type="date"
          required
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          data-testid="need-date"
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="text-sm text-slate-600">宠物种类</label>
          <input
            name="petSpecies"
            required
            placeholder="如：猫、小型犬"
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            data-testid="need-species"
          />
        </div>
        <div>
          <label className="text-sm text-slate-600">体重（kg）</label>
          <input
            name="petWeightKg"
            type="number"
            step="0.1"
            min="0.1"
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            data-testid="need-weight"
          />
        </div>
      </div>
      <div>
        <label className="text-sm text-slate-600">说明（健康、笼具、文件进度等）</label>
        <textarea
          name="petNotes"
          required
          rows={4}
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          data-testid="need-notes"
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="text-sm text-slate-600">预算下限</label>
          <input
            name="budgetMin"
            type="number"
            step="0.01"
            min="0"
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            data-testid="need-budget-min"
          />
        </div>
        <div>
          <label className="text-sm text-slate-600">预算上限</label>
          <input
            name="budgetMax"
            type="number"
            step="0.01"
            min="0"
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            data-testid="need-budget-max"
          />
        </div>
      </div>
      <div>
        <label className="text-sm text-slate-600">货币</label>
        <input name="currency" defaultValue="CNY" className="mt-1 w-full rounded border border-slate-300 px-3 py-2" />
      </div>
      <label className="flex items-start gap-2 text-sm text-slate-700">
        <input type="checkbox" name="ackNeed" required className="mt-1" />
        <span>
          需求方：本人了解目的地对活体入境的法规与检疫要求，并自行承担合规责任；平台不提供法律或运输保证。
        </span>
      </label>
      {state?.error ? <p className="text-sm text-red-600">{state.error}</p> : null}
      <Submit />
    </form>
  );
}
