"use client";

import { createReportAction } from "@/actions/report";
import { useFormState, useFormStatus } from "react-dom";

const initial = { error: "" as string, ok: false };

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded border border-red-200 bg-red-50 px-3 py-1.5 text-sm text-red-900 hover:bg-red-100 disabled:opacity-60"
    >
      {pending ? "提交中…" : "提交举报"}
    </button>
  );
}

export function ReportForm({
  targetType,
  targetId,
  label = "举报此内容",
}: {
  targetType: "offer" | "need" | "match";
  targetId: string;
  label?: string;
}) {
  const [state, formAction] = useFormState(createReportAction, initial);

  return (
    <div className="mt-6 rounded border border-slate-200 bg-slate-50 p-4">
      <h3 className="text-sm font-medium text-slate-800">{label}</h3>
      <p className="mt-1 text-xs text-slate-500">
        平台仅记录举报信息供管理员查看，不构成对内容的法律认定。请勿恶意举报。
      </p>
      <form action={formAction} className="mt-3 space-y-2">
        <input type="hidden" name="targetType" value={targetType} />
        <input type="hidden" name="targetId" value={targetId} />
        <textarea
          name="reason"
          required
          minLength={5}
          maxLength={2000}
          rows={3}
          placeholder="请简要说明原因（至少 5 字）"
          className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          data-testid="report-reason"
        />
        {state?.error ? <p className="text-sm text-red-600">{state.error}</p> : null}
        {state?.ok ? <p className="text-sm text-green-700">已收到，感谢反馈。</p> : null}
        <Submit />
      </form>
    </div>
  );
}
