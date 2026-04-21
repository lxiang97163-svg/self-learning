import { prisma } from "@/lib/prisma";
import { requireAdmin } from "@/lib/session";

export default async function AdminPage() {
  await requireAdmin();

  const [users, offers, needs, reports] = await Promise.all([
    prisma.user.findMany({ orderBy: { createdAt: "desc" }, take: 50 }),
    prisma.petCarryOffer.findMany({ orderBy: { createdAt: "desc" }, take: 50, include: { owner: true } }),
    prisma.petCarryNeed.findMany({ orderBy: { createdAt: "desc" }, take: 50, include: { owner: true } }),
    prisma.report.findMany({ orderBy: { createdAt: "desc" }, take: 50 }),
  ]);

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold">管理后台（极简）</h1>
      <p className="text-sm text-slate-600">仅 admin 角色可见。管理员通过环境变量种子创建，见 README。</p>

      <section>
        <h2 className="text-lg font-medium">用户</h2>
        <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2">邮箱</th>
                <th className="px-3 py-2">角色</th>
                <th className="px-3 py-2">显示名</th>
                <th className="px-3 py-2">创建时间</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-slate-100">
                  <td className="px-3 py-2">{u.email}</td>
                  <td className="px-3 py-2">{u.role}</td>
                  <td className="px-3 py-2">{u.displayName}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{u.createdAt.toISOString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium">帖子：携带意向</h2>
        <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2">ID</th>
                <th className="px-3 py-2">路线</th>
                <th className="px-3 py-2">发布者</th>
                <th className="px-3 py-2">状态</th>
              </tr>
            </thead>
            <tbody>
              {offers.map((o) => (
                <tr key={o.id} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-mono text-xs">{o.id.slice(0, 8)}…</td>
                  <td className="px-3 py-2">
                    {o.originCity} → {o.destinationCity}
                  </td>
                  <td className="px-3 py-2">{o.owner.email}</td>
                  <td className="px-3 py-2">{o.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium">帖子：宠物帮带需求</h2>
        <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2">ID</th>
                <th className="px-3 py-2">目的地 / 宠物</th>
                <th className="px-3 py-2">发布者</th>
                <th className="px-3 py-2">状态</th>
              </tr>
            </thead>
            <tbody>
              {needs.map((n) => (
                <tr key={n.id} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-mono text-xs">{n.id.slice(0, 8)}…</td>
                  <td className="px-3 py-2">
                    {n.destinationCity} · {n.petSpecies}
                  </td>
                  <td className="px-3 py-2">{n.owner.email}</td>
                  <td className="px-3 py-2">{n.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium">举报（占位）</h2>
        <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2">目标</th>
                <th className="px-3 py-2">原因</th>
                <th className="px-3 py-2">时间</th>
              </tr>
            </thead>
            <tbody>
              {reports.length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-slate-500" colSpan={3}>
                    暂无举报记录。
                  </td>
                </tr>
              ) : (
                reports.map((rep) => (
                  <tr key={rep.id} className="border-t border-slate-100">
                    <td className="px-3 py-2">
                      {rep.targetType} / {rep.targetId.slice(0, 8)}…
                    </td>
                    <td className="px-3 py-2">{rep.reason}</td>
                    <td className="px-3 py-2 text-xs">{rep.createdAt.toISOString()}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
