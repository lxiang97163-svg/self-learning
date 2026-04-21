"use client";

import { sendMessageAction } from "@/actions/message";
import { useFormState, useFormStatus } from "react-dom";

const initial = { error: "" as string };

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-60"
      data-testid="send-message"
    >
      {pending ? "发送中…" : "发送"}
    </button>
  );
}

export function ThreadForm({ threadId }: { threadId: string }) {
  const [state, formAction] = useFormState(sendMessageAction, initial);

  return (
    <form action={formAction} className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
      <input type="hidden" name="threadId" value={threadId} />
      <input
        name="body"
        required
        placeholder="输入消息（撮合已接受且未完成交割前）"
        className="min-w-[200px] flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
        data-testid="message-body"
      />
      <Submit />
      {state?.error ? <p className="w-full text-sm text-red-600">{state.error}</p> : null}
    </form>
  );
}
