"use client";

import { createPetCarryOfferAction } from "@/actions/offer";
import { useFormState, useFormStatus } from "react-dom";

const initial = { error: "" as string };

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
      data-testid="offer-submit"
    >
      {pending ? "提交中…" : "发布携带意向"}
    </button>
  );
}

export function OfferForm() {
  const [state, formAction] = useFormState(createPetCarryOfferAction, initial);

  return (
    <form action={formAction} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="text-sm text-slate-600">出发城市</label>
          <input
            name="originCity"
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            data-testid="offer-origin"
          />
        </div>
        <div>
          <label className="text-sm text-slate-600">目的地城市</label>
          <input
            name="destinationCity"
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            data-testid="offer-dest"
          />
        </div>
      </div>
      <div>
        <label className="text-sm text-slate-600">航班日期</label>
        <input
          name="flightDate"
          type="date"
          required
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          data-testid="offer-date"
        />
      </div>
      <div>
        <label className="text-sm text-slate-600">可接受的宠物类型（简述）</label>
        <input
          name="acceptedSpecies"
          required
          placeholder="如：猫、小型犬（需进客舱）"
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          data-testid="offer-species"
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="text-sm text-slate-600">宠物体重上限（kg）</label>
          <input
            name="maxPetWeightKg"
            type="number"
            step="0.1"
            min="0.1"
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            data-testid="offer-maxkg"
          />
        </div>
        <div>
          <label className="text-sm text-slate-600">携带方式意向</label>
          <select
            name="carryMode"
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            data-testid="offer-carryMode"
            defaultValue="either"
          >
            <option value="cabin">客舱</option>
            <option value="hold">托运舱</option>
            <option value="either">可商议</option>
          </select>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="text-sm text-slate-600">计价方式</label>
          <select name="priceModel" className="mt-1 w-full rounded border border-slate-300 px-3 py-2" data-testid="offer-priceModel">
            <option value="perPet">perPet（每只）</option>
            <option value="fixed">fixed（一口价）</option>
          </select>
        </div>
        <div>
          <label className="text-sm text-slate-600">价格 / 单价</label>
          <input
            name="price"
            type="number"
            step="0.01"
            min="0"
            required
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            data-testid="offer-price"
          />
        </div>
      </div>
      <div>
        <label className="text-sm text-slate-600">货币（默认 CNY）</label>
        <input name="currency" defaultValue="CNY" className="mt-1 w-full rounded border border-slate-300 px-3 py-2" />
      </div>
      <div>
        <label className="text-sm text-slate-600">补充说明（可选）</label>
        <textarea name="notes" rows={2} className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm" />
      </div>
      <label className="flex items-start gap-2 text-sm text-slate-700">
        <input type="checkbox" name="ackCarrier" required className="mt-1" />
        <span>
          携带方：本人了解航司与目的地对活体运输的规定，对申报与交接的真实性负责；平台不承运、不代理报关。
        </span>
      </label>
      {state?.error ? <p className="text-sm text-red-600">{state.error}</p> : null}
      <Submit />
    </form>
  );
}
