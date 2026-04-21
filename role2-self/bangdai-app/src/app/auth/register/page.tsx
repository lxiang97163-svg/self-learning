import Link from "next/link";
import { RegisterForm } from "./register-form";

export default function RegisterPage() {
  return (
    <div className="mx-auto max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-xl font-semibold">注册</h1>
      <p className="mt-2 text-sm text-slate-600">
        已有账号？{" "}
        <Link className="underline" href="/auth/login">
          登录
        </Link>
      </p>
      <div className="mt-6">
        <RegisterForm />
      </div>
    </div>
  );
}
