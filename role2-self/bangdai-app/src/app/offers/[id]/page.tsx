import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { ReportForm } from "@/components/report-form";
import { InterestOnOfferForm } from "./interest-on-offer-form";

export default async function OfferDetailPage({ params }: { params: { id: string } }) {
  const offer = await prisma.petCarryOffer.findUnique({
    where: { id: params.id },
    include: { owner: { select: { id: true, displayName: true, email: true } } },
  });
  if (!offer) notFound();

  const session = await getServerSession(authOptions);
  const uid = session?.user?.id;

  const myNeeds =
    uid && uid !== offer.ownerId
      ? await prisma.petCarryNeed.findMany({
          where: {
            ownerId: uid,
            destinationCity: offer.destinationCity,
            status: "open",
          },
          orderBy: { createdAt: "desc" },
        })
      : [];

  const needOptions = myNeeds.map((n) => ({
    id: n.id,
    label: `${n.petSpecies} · ${n.petWeightKg} kg · 预算 ${n.budgetMin}-${n.budgetMax} ${n.currency}`,
  }));

  const carryLabel =
    offer.carryMode === "cabin" ? "客舱" : offer.carryMode === "hold" ? "托运舱" : "可商议";

  return (
    <div className="space-y-6">
      <Link href="/offers" className="text-sm text-slate-600 hover:underline">
        ← 携带意向列表
      </Link>
      <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold">
          {offer.originCity} → {offer.destinationCity}
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          航班 {offer.flightDate.toISOString().slice(0, 10)} · 接受 {offer.acceptedSpecies} · 限重 ≤
          {offer.maxPetWeightKg} kg · {carryLabel} · {offer.priceModel} · {offer.price} {offer.currency} · 状态{" "}
          {offer.status}
        </p>
        {offer.notes ? (
          <p className="mt-2 text-sm text-slate-800 whitespace-pre-wrap">{offer.notes}</p>
        ) : null}
        <p className="mt-2 text-sm text-slate-600">携带方：{offer.owner.displayName}</p>

        {uid === offer.ownerId ? (
          <p className="mt-4 text-sm text-slate-500">这是您发布的携带意向。</p>
        ) : uid ? (
          <div className="mt-6 border-t border-slate-100 pt-4">
            <h2 className="text-sm font-medium text-slate-800">表达兴趣</h2>
            <p className="mt-1 text-xs text-slate-500">
              在携带意向页用「我的需求」发起撮合；需求方也可在需求详情页选择开放中的携带意向（二选一）。
            </p>
            <div className="mt-3">
              <InterestOnOfferForm offerId={offer.id} needOptions={needOptions} />
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
        {uid ? <ReportForm targetType="offer" targetId={offer.id} /> : null}
      </div>
    </div>
  );
}
