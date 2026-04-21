import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { ReportForm } from "@/components/report-form";
import { InterestOnNeedForm } from "./interest-on-need-form";

export default async function NeedDetailPage({ params }: { params: { id: string } }) {
  const need = await prisma.petCarryNeed.findUnique({
    where: { id: params.id },
    include: { owner: { select: { id: true, displayName: true } } },
  });
  if (!need) notFound();

  const session = await getServerSession(authOptions);
  const uid = session?.user?.id;

  const myOffers =
    uid && uid !== need.ownerId
      ? await prisma.petCarryOffer.findMany({
          where: {
            ownerId: uid,
            destinationCity: need.destinationCity,
            status: "open",
          },
          orderBy: { flightDate: "asc" },
        })
      : [];

  const offerOptions = myOffers.map((o) => ({
    id: o.id,
    label: `${o.originCity} → ${o.destinationCity} · ${o.flightDate.toISOString().slice(0, 10)} · 限${o.maxPetWeightKg}kg`,
  }));

  return (
    <div className="space-y-6">
      <Link href="/needs" className="text-sm text-slate-600 hover:underline">
        ← 需求列表
      </Link>
      <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold">
          {need.destinationCity} · {need.petSpecies}（{need.petWeightKg} kg）
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          希望 {need.neededByDate.toISOString().slice(0, 10)} 前到达 · 预算 {need.budgetMin}–{need.budgetMax} {need.currency}{" "}
          · 状态 {need.status}
        </p>
        {need.originCity ? <p className="mt-1 text-sm text-slate-600">出发地：{need.originCity}</p> : null}
        <p className="mt-3 text-sm text-slate-800 whitespace-pre-wrap">{need.petNotes}</p>
        <p className="mt-2 text-sm text-slate-500">需求方：{need.owner.displayName}</p>

        {uid === need.ownerId ? (
          <p className="mt-4 text-sm text-slate-500">这是您发布的需求。</p>
        ) : uid ? (
          <div className="mt-6 border-t border-slate-100 pt-4">
            <h2 className="text-sm font-medium text-slate-800">表达兴趣</h2>
            <p className="mt-1 text-xs text-slate-500">
              在需求页用「我的携带意向」发起撮合；与携带意向页用「我的需求」发起二选一即可。
            </p>
            <div className="mt-3">
              <InterestOnNeedForm needId={need.id} offerOptions={offerOptions} />
            </div>
          </div>
        ) : (
          <p className="mt-4 text-sm text-amber-800">
            请{" "}
            <Link className="underline" href="/auth/login">
              登录
            </Link>{" "}
            后表达兴趣。
          </p>
        )}
        {uid ? <ReportForm targetType="need" targetId={need.id} /> : null}
      </div>
    </div>
  );
}
