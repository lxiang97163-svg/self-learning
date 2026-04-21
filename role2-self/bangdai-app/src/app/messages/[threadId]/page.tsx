import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { requireAuth } from "@/lib/session";
import { ThreadForm } from "./thread-form";

export default async function ThreadPage({ params }: { params: { threadId: string } }) {
  const session = await requireAuth();
  const uid = session.user.id;

  const m = await prisma.petCarryMatch.findUnique({
    where: { id: params.threadId },
    include: { offer: true, need: true },
  });
  if (!m) notFound();

  if (uid !== m.offer.ownerId && uid !== m.need.ownerId) {
    return (
      <p className="text-sm text-red-600">
        无权查看此会话。{" "}
        <Link className="underline" href="/messages">
          返回
        </Link>
      </p>
    );
  }

  const messages = await prisma.message.findMany({
    where: { threadId: m.id },
    orderBy: { createdAt: "asc" },
    include: { sender: { select: { displayName: true, email: true } } },
  });

  const canSend = m.status === "accepted";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Link href="/messages" className="text-sm text-slate-600 hover:underline">
          ← 会话列表
        </Link>
        <Link className="text-sm text-slate-700 underline" href={`/matches/${m.id}`}>
          撮合单详情
        </Link>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h1 className="text-lg font-semibold">会话</h1>
        <p className="text-xs text-slate-500">threadId = {m.id}</p>
        {!canSend ? (
          <p className="mt-2 text-sm text-amber-800">
            当前状态不可发新消息（需为「已接受」且未完成交割）。
          </p>
        ) : null}
        <ul className="mt-4 space-y-3">
          {messages.length === 0 ? (
            <li className="text-sm text-slate-500">暂无消息。</li>
          ) : (
            messages.map((msg) => (
              <li key={msg.id} className="rounded bg-slate-50 p-3 text-sm">
                <div className="text-xs text-slate-500">
                  {msg.sender.displayName} · {msg.createdAt.toISOString()}
                </div>
                <div className="mt-1 whitespace-pre-wrap text-slate-800">{msg.body}</div>
              </li>
            ))
          )}
        </ul>
        {canSend ? <ThreadForm threadId={m.id} /> : null}
      </div>
    </div>
  );
}
