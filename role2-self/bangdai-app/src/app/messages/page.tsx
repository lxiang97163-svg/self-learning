import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { requireAuth } from "@/lib/session";

export default async function MessagesIndexPage() {
  const session = await requireAuth();
  const uid = session.user.id;

  const threads = await prisma.petCarryMatch.findMany({
    where: {
      OR: [{ offer: { ownerId: uid } }, { need: { ownerId: uid } }],
    },
    include: {
      offer: true,
      need: true,
    },
    orderBy: { createdAt: "desc" },
  });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">会话列表</h1>
      <p className="text-sm text-slate-600">会话与撮合单一一对应（threadId = 撮合单 ID）。</p>
      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {threads.length === 0 ? (
          <li className="p-6 text-sm text-slate-600">暂无会话。请先完成撮合并接受。</li>
        ) : (
          threads.map((t) => (
            <li key={t.id} className="p-4 hover:bg-slate-50">
              <Link href={`/messages/${t.id}`} className="block">
                <div className="flex flex-wrap justify-between gap-2 text-sm">
                  <span className="font-medium">
                    {t.offer.originCity}→{t.offer.destinationCity} · {t.need.petSpecies}
                  </span>
                  <span className="text-slate-500">{t.status}</span>
                </div>
                <div className="mt-1 text-xs text-slate-500">撮合 {t.id.slice(0, 8)}…</div>
              </Link>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
