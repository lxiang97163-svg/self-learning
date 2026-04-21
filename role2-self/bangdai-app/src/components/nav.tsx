import Link from "next/link";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { LogoutButton } from "./logout-button";

export async function Nav() {
  const session = await getServerSession(authOptions);

  return (
    <header className="sticky top-0 z-50 border-b border-slate-200/80 bg-white/75 shadow-sm backdrop-blur-md supports-[backdrop-filter]:bg-white/60">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-4 px-4 py-3.5 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="group flex items-baseline gap-2 text-lg font-semibold tracking-tight text-slate-900"
        >
          <span className="bg-gradient-to-r from-brand-600 to-violet-600 bg-clip-text text-transparent transition-opacity group-hover:opacity-90">
            宠物帮带
          </span>
          <span className="text-slate-400">·</span>
          <span className="font-medium text-slate-700">CarryLink</span>
        </Link>
        <nav className="flex flex-wrap items-center gap-1 text-sm text-slate-600 sm:gap-1.5">
          <Link
            className="rounded-full px-3 py-1.5 transition-colors hover:bg-slate-100 hover:text-slate-900"
            href="/offers"
          >
            携带意向
          </Link>
          <Link
            className="rounded-full px-3 py-1.5 transition-colors hover:bg-slate-100 hover:text-slate-900"
            href="/needs"
          >
            需求
          </Link>
          <Link
            className="rounded-full px-3 py-1.5 transition-colors hover:bg-slate-100 hover:text-slate-900"
            href="/messages"
          >
            消息
          </Link>
          <Link
            className="rounded-full px-3 py-1.5 transition-colors hover:bg-slate-100 hover:text-slate-900"
            href="/legal/disclaimer"
          >
            免责
          </Link>
          <Link
            className="rounded-full px-3 py-1.5 transition-colors hover:bg-slate-100 hover:text-slate-900"
            href="/legal/prohibited"
          >
            禁运
          </Link>
          {session?.user?.role === "admin" && (
            <Link
              className="rounded-full px-3 py-1.5 font-medium text-amber-800 transition-colors hover:bg-amber-50"
              href="/admin"
            >
              管理
            </Link>
          )}
          {session ? (
            <span className="ml-1 flex items-center gap-2 border-l border-slate-200 pl-3 sm:ml-2">
              <span className="max-w-[10rem] truncate text-xs text-slate-500 sm:max-w-xs sm:text-sm">
                {session.user.email}
              </span>
              <LogoutButton />
            </span>
          ) : (
            <span className="ml-1 flex items-center gap-2 border-l border-slate-200 pl-3 sm:ml-2">
              <Link
                className="rounded-full border border-slate-200 bg-white px-3.5 py-1.5 font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
                href="/auth/login"
              >
                登录
              </Link>
              <Link
                className="rounded-full bg-gradient-to-r from-brand-600 to-violet-600 px-3.5 py-1.5 font-medium text-white shadow-md shadow-brand-500/25 transition hover:brightness-105"
                href="/auth/register"
              >
                注册
              </Link>
            </span>
          )}
        </nav>
      </div>
    </header>
  );
}
