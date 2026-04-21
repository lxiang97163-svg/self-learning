"use client";

import { completeDeliveryAction, saveAgreedAmountAction } from "@/actions/match";
import { useFormState, useFormStatus } from "react-dom";

const initialAmount = { error: "" as string, ok: false };
const initialComplete = { error: "" as string, ok: false };

function AmountSubmit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-60"
      data-testid="save-amount"
    >
      {pending ? "保存中…" : "记录约定金额"}
    </button>
  );
}

function CompleteSubmit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded border border-emerald-700 bg-emerald-50 px-3 py-1.5 text-sm text-emerald-900 disabled:opacity-60"
      data-testid="complete-delivery"
    >
      {pending ? "处理中…" : "标记交割完成"}
    </button>
  );
}

export function AmountForms({
  matchId,
  agreedAmount,
  platformFeeRate,
  platformFeeAmount,
  canEdit,
  status,
}: {
  matchId: string;
  agreedAmount: number | null;
  platformFeeRate: number | null;
  platformFeeAmount: number | null;
  canEdit: boolean;
  status: string;
}) {
  const [amountState, amountAction] = useFormState(saveAgreedAmountAction, initialAmount);
  const [completeState, completeAction] = useFormState(completeDeliveryAction, initialComplete);

  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
      <h3 className="text-sm font-medium text-slate-800">约定金额与平台费试算</h3>
      <p className="text-xs text-slate-500">
        金额为双方在平台内确认的「成交金额」字段；线下付款由双方自理。平台费率为环境变量配置，仅作试算展示。
      </p>
      {agreedAmount != null && platformFeeRate != null && platformFeeAmount != null ? (
        <ul className="text-sm text-slate-700">
          <li>约定金额：{agreedAmount}</li>
          <li>费率：{(platformFeeRate * 100).toFixed(2)}%</li>
          <li>试算平台费：{platformFeeAmount}</li>
        </ul>
      ) : (
        <p className="text-sm text-slate-600">尚未记录约定金额。</p>
      )}

      {canEdit && status === "accepted" ? (
        <form action={amountAction} className="flex flex-wrap items-end gap-2">
          <input type="hidden" name="matchId" value={matchId} />
          <div>
            <label className="text-xs text-slate-500">约定金额（CNY 或所选货币一致即可）</label>
            <input
              name="agreedAmount"
              type="number"
              step="0.01"
              min="0.01"
              required
              className="mt-1 block rounded border border-slate-300 px-3 py-1.5 text-sm"
              data-testid="agreed-amount"
            />
          </div>
          <AmountSubmit />
        </form>
      ) : null}
      {amountState?.error ? <p className="text-sm text-red-600">{amountState.error}</p> : null}
      {amountState?.ok ? <p className="text-sm text-green-700">已保存约定金额。</p> : null}

      {canEdit && status === "accepted" && agreedAmount != null ? (
        <form action={completeAction}>
          <input type="hidden" name="matchId" value={matchId} />
          <CompleteSubmit />
        </form>
      ) : null}
      {completeState?.error ? <p className="text-sm text-red-600">{completeState.error}</p> : null}
      {completeState?.ok ? <p className="text-sm text-green-700">已标记交割完成（业务闭环，不代表资金已付）。</p> : null}
    </div>
  );
}
