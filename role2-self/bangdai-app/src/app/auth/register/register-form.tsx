"use client";

import { registerAction } from "@/actions/auth";
import { useFormState, useFormStatus } from "react-dom";

const initial = { error: "" as string };

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
    >
      {pending ? "提交中…" : "注册"}
    </button>
  );
}

export function RegisterForm() {
  const [state, formAction] = useFormState(registerAction, initial);

  return (
    <form action={formAction} className="space-y-4">
      <div>
        <label className="block text-sm text-slate-600">显示名</label>
        <input
          name="displayName"
          required
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          data-testid="register-displayName"
        />
      </div>
      <div>
        <label className="block text-sm text-slate-600">邮箱</label>
        <input
          name="email"
          type="email"
          required
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          data-testid="register-email"
        />
      </div>
      <div>
        <label className="block text-sm text-slate-600">密码（≥8 位）</label>
        <input
          name="password"
          type="password"
          required
          minLength={8}
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          data-testid="register-password"
        />
      </div>

      <label className="flex items-start gap-2 text-sm text-slate-700">
        <input type="checkbox" name="ackTraveler" required className="mt-1" data-testid="ack-traveler" />
        <span>
          携带方：本人了解航司与目的地对活体运输的规定，并对申报与交接的真实性负责。
        </span>
      </label>
      <label className="flex items-start gap-2 text-sm text-slate-700">
        <input type="checkbox" name="ackRequester" required className="mt-1" data-testid="ack-requester" />
        <span>需求方：本人了解目的地检疫与入境规则，不对平台做合规背书。</span>
      </label>
      <label className="flex items-start gap-2 text-sm text-slate-700">
        <input type="checkbox" name="ackProhibited" required className="mt-1" data-testid="ack-prohibited" />
        <span>已阅读并同意遵守《禁运与风险提示》，不上传违法或禁运内容。</span>
      </label>

      {state?.error ? <p className="text-sm text-red-600">{state.error}</p> : null}

      <Submit />
    </form>
  );
}
