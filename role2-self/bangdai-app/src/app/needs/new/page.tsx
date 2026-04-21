import Link from "next/link";
import { requireAuth } from "@/lib/session";
import { NeedForm } from "./need-form";

export default async function NewNeedPage() {
  await requireAuth();

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <Link href="/needs" className="text-sm text-slate-600 hover:underline">
          ← 返回需求列表
        </Link>
        <h1 className="mt-2 text-xl font-semibold">发布宠物帮带需求</h1>
        <p className="mt-1 text-sm text-slate-600">请如实填写宠物与行程；合规与检疫由您自行确认。</p>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <NeedForm />
      </div>
    </div>
  );
}
