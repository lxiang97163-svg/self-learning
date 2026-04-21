import Link from "next/link";
import { prisma } from "@/lib/prisma";

export default async function OffersPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const dest = typeof searchParams.dest === "string" ? searchParams.dest.trim() : "";
  const from = typeof searchParams.from === "string" ? searchParams.from : "";
  const to = typeof searchParams.to === "string" ? searchParams.to : "";

  const offers = await prisma.petCarryOffer.findMany({
    where: {
      status: "open",
      ...(dest ? { destinationCity: { contains: dest } } : {}),
      ...(from && to
        ? {
            flightDate: {
              gte: new Date(from),
              lte: new Date(to + "T23:59:59.999Z"),
            },
          }
        : {}),
    },
    orderBy: { flightDate: "asc" },
    include: { owner: { select: { displayName: true, email: true } } },
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">携带意向</h1>
          <p className="text-sm text-slate-600">国际航班宠物帮带 · 筛选目的地与航班日期（可选）</p>
        </div>
        <Link
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
          href="/offers/new"
        >
          发布携带意向
        </Link>
      </div>

      <form className="flex flex-wrap gap-3 rounded-lg border border-slate-200 bg-white p-4" method="get">
        <div>
          <label className="text-xs text-slate-500">目的地</label>
          <input
            name="dest"
            defaultValue={dest}
            placeholder="如 洛杉矶"
            className="mt-1 block rounded border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-500">日期从</label>
          <input
            name="from"
            type="date"
            defaultValue={from}
            className="mt-1 block rounded border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-500">日期到</label>
          <input
            name="to"
            type="date"
            defaultValue={to}
            className="mt-1 block rounded border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <button type="submit" className="self-end rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          筛选
        </button>
      </form>

      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {offers.length === 0 ? (
          <li className="p-6 text-sm text-slate-600">暂无开放中的携带意向。</li>
        ) : (
          offers.map((o) => (
            <li key={o.id} className="p-4 hover:bg-slate-50">
              <Link href={`/offers/${o.id}`} className="block">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">
                    {o.originCity} → {o.destinationCity}
                  </span>
                  <span className="text-sm text-slate-500">{o.flightDate.toISOString().slice(0, 10)}</span>
                </div>
                <div className="mt-1 text-sm text-slate-600">
                  接受 {o.acceptedSpecies} · 限重 ≤{o.maxPetWeightKg} kg · {o.priceModel} · {o.price} {o.currency} ·{" "}
                  {o.owner.displayName}
                </div>
              </Link>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
