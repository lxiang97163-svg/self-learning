import Link from "next/link";

export default function Home() {
  return (
    <div className="space-y-10">
      <section className="relative overflow-hidden rounded-2xl border border-slate-200/80 bg-white p-8 shadow-card sm:p-10">
        <div
          className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-gradient-to-br from-brand-400/20 to-violet-400/10 blur-3xl"
          aria-hidden
        />
        <div className="relative">
          <p className="text-xs font-medium uppercase tracking-widest text-brand-600/90">演示环境</p>
          <h1 className="mt-3 max-w-3xl text-balance text-3xl font-bold leading-tight tracking-tight text-slate-900 sm:text-4xl">
            国际航班
            <span className="mx-2 inline-block align-middle text-slate-300 sm:mx-3">×</span>
            宠物帮带撮合
          </h1>
          <p className="mt-5 max-w-2xl text-pretty text-base leading-relaxed text-slate-600 sm:text-lg">
            CarryLink 聚焦「旅客携带意向」与「宠物帮带需求」的信息发布与撮合。平台仅记录双方确认的约定金额并试算服务费比例；不提供运输、不持有动物、不代理报关与检疫，也不提供应用内支付。
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              className="inline-flex items-center justify-center rounded-full bg-gradient-to-r from-brand-600 to-violet-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-brand-500/30 transition hover:brightness-105"
              href="/auth/register"
            >
              免费注册
            </Link>
            <Link
              className="inline-flex items-center justify-center rounded-full border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-slate-800 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
              href="/auth/login"
            >
              登录
            </Link>
            <span className="hidden h-6 w-px bg-slate-200 sm:block" aria-hidden />
            <Link
              className="text-sm font-medium text-brand-700 underline decoration-brand-300 underline-offset-4 transition hover:text-brand-800"
              href="/offers"
            >
              浏览携带意向
            </Link>
            <Link
              className="text-sm font-medium text-brand-700 underline decoration-brand-300 underline-offset-4 transition hover:text-brand-800"
              href="/needs"
            >
              浏览需求
            </Link>
          </div>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-soft backdrop-blur-sm">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-100 text-sm font-bold text-brand-800"
            aria-hidden
          >
            携
          </div>
          <h2 className="mt-3 text-sm font-semibold text-slate-900">携带方</h2>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-600">发布航班与可接受的宠物类型、体重上限与计价方式，等待需求方表达兴趣。</p>
        </div>
        <div className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-soft backdrop-blur-sm">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-100 text-sm font-bold text-violet-800"
            aria-hidden
          >
            需
          </div>
          <h2 className="mt-3 text-sm font-semibold text-slate-900">需求方</h2>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-600">发布宠物种类、体重与目的地窗口，匹配合适携带意向并站内沟通约定。</p>
        </div>
        <div className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-soft backdrop-blur-sm">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-sm font-bold text-slate-700"
            aria-hidden
          >
            界
          </div>
          <h2 className="mt-3 text-sm font-semibold text-slate-900">平台边界</h2>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-600">撮合与记录为主；资金与检疫手续在线下自行完成。</p>
        </div>
      </section>

      <section className="rounded-2xl border border-amber-200/80 bg-gradient-to-br from-amber-50 to-orange-50/50 p-6 shadow-soft">
        <p className="text-sm leading-relaxed text-amber-950">
          <strong className="font-semibold">合规提示（非法律意见）：</strong>
          活体跨境涉及检疫、航司与目的地法规；用户须自行完成合规手续。请勿发布违法或虐待内容。详见{" "}
          <Link className="font-medium text-amber-900 underline decoration-amber-400/80 underline-offset-2" href="/legal/prohibited">
            《禁运与风险提示》
          </Link>
          。
        </p>
      </section>
    </div>
  );
}
