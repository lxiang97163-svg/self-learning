"use client";

import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setPending(true);
    const form = e.currentTarget;
    const fd = new FormData(form);
    const email = String(fd.get("email") || "");
    const password = String(fd.get("password") || "");
    const res = await signIn("credentials", {
      email,
      password,
      redirect: false,
    });
    setPending(false);
    if (res?.error) {
      setError("邮箱或密码错误。");
      return;
    }
    router.push("/offers");
    router.refresh();
  }

  const registered = searchParams.get("registered");

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {registered ? <p className="text-sm text-green-700">注册成功，请登录。</p> : null}
      <div>
        <label className="block text-sm text-slate-600">邮箱</label>
        <input
          name="email"
          type="email"
          required
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          data-testid="login-email"
        />
      </div>
      <div>
        <label className="block text-sm text-slate-600">密码</label>
        <input
          name="password"
          type="password"
          required
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          data-testid="login-password"
        />
      </div>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      <button
        type="submit"
        disabled={pending}
        className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        data-testid="login-submit"
      >
        {pending ? "登录中…" : "登录"}
      </button>
    </form>
  );
}
