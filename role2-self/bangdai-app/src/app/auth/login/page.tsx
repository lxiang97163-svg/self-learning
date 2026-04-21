import Link from "next/link";
import { Suspense } from "react";
import { LoginForm } from "./login-form";

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-xl font-semibold">登录</h1>
      <p className="mt-2 text-sm text-slate-600">
        没有账号？{" "}
        <Link className="underline" href="/auth/register">
          注册
        </Link>
      </p>
      <div className="mt-6">
        <Suspense fallback={<p className="text-sm text-slate-500">加载中…</p>}>
          <LoginForm />
        </Suspense>
      </div>
    </div>
  );
}
