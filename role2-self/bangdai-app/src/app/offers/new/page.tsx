import Link from "next/link";
import { requireAuth } from "@/lib/session";
import { OfferForm } from "./offer-form";

export default async function NewOfferPage() {
  await requireAuth();

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <Link href="/offers" className="text-sm text-slate-600 hover:underline">
          ← 返回携带意向列表
        </Link>
        <h1 className="mt-2 text-xl font-semibold">发布携带意向</h1>
        <p className="mt-1 text-sm text-slate-600">
          仅发布航班与可协助范围；检疫、航司规定与线下交接由双方自行确认。
        </p>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <OfferForm />
      </div>
    </div>
  );
}
