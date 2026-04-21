import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { ReportForm } from "@/components/report-form";
import { MatchActions } from "./match-actions";
import { AmountForms } from "./amount-forms";

function counterpartyId(offerOwnerId: string, needOwnerId: string, fromUserId: string) {
  return fromUserId === offerOwnerId ? needOwnerId : offerOwnerId;
}

export default async function MatchPage({ params }: { params: { id: string } }) {
  const m = await prisma.petCarryMatch.findUnique({
    where: { id: params.id },
    include: {
      offer: { include: { owner: true } },
      need: { include: { owner: true } },
      commission: true,
    },
  });
  if (!m) notFound();

  const session = await getServerSession(authOptions);
  const uid = session?.user?.id;
  const cp = counterpartyId(m.offer.ownerId, m.need.ownerId, m.fromUserId);
  const isParticipant = uid === m.offer.ownerId || uid === m.need.ownerId;
  const canCounterpartyAct = uid === cp && m.status === "pending";

  return (
    <div className="space-y-6">
      <Link href="/messages" className="text-sm text-slate-600 hover:underline">
        ← 返回会话列表
      </Link>

      <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold">撮合单（宠物帮带）</h1>
        <p className="mt-1 text-sm text-slate-500">ID：{m.id}</p>
        <p className="mt-2 text-sm">
          状态：<span className="font-medium">{m.status}</span>
        </p>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div className="rounded border border-slate-100 p-3">
            <h2 className="text-sm font-medium text-slate-800">携带意向</h2>
            <p className="mt-1 text-sm text-slate-600">
              {m.offer.originCity} → {m.offer.destinationCity} · {m.offer.flightDate.toISOString().slice(0, 10)}
            </p>
            <p className="text-xs text-slate-500">携带方：{m.offer.owner.displayName}</p>
            <Link className="mt-2 inline-block text-sm text-slate-700 underline" href={`/offers/${m.offerId}`}>
              查看携带意向
            </Link>
          </div>
          <div className="rounded border border-slate-100 p-3">
            <h2 className="text-sm font-medium text-slate-800">需求</h2>
            <p className="mt-1 text-sm text-slate-600">
              {m.need.destinationCity} · {m.need.petSpecies} · {m.need.petWeightKg} kg
            </p>
            <p className="text-xs text-slate-500">需求方：{m.need.owner.displayName}</p>
            <Link className="mt-2 inline-block text-sm text-slate-700 underline" href={`/needs/${m.needId}`}>
              查看需求
            </Link>
          </div>
        </div>

        <p className="mt-4 text-sm text-slate-600">
          发起方：{m.fromUserId === m.offer.ownerId ? "携带方" : "需求方"}（用户 ID {m.fromUserId.slice(0, 8)}…）
        </p>

        {canCounterpartyAct ? (
          <div className="mt-6 border-t border-slate-100 pt-4">
            <p className="mb-2 text-sm text-slate-700">对方已表达兴趣，您可以：</p>
            <MatchActions matchId={m.id} />
          </div>
        ) : null}

        {isParticipant && m.status === "accepted" ? (
          <div className="mt-6">
            <Link
              className="text-sm font-medium text-slate-900 underline"
              href={`/messages/${m.id}`}
              data-testid="open-messages"
            >
              进入站内消息
            </Link>
          </div>
        ) : null}

        {isParticipant ? (
          <div className="mt-6">
            <AmountForms
              matchId={m.id}
              agreedAmount={m.commission?.agreedAmount ?? null}
              platformFeeRate={m.commission?.platformFeeRate ?? null}
              platformFeeAmount={m.commission?.platformFeeAmount ?? null}
              canEdit={true}
              status={m.status}
            />
          </div>
        ) : (
          <p className="mt-6 text-sm text-amber-800">您不是该撮合参与方。</p>
        )}
        {uid ? <ReportForm targetType="match" targetId={m.id} label="举报此撮合单" /> : null}
      </div>
    </div>
  );
}
