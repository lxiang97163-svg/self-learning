"use server";

import { prisma } from "@/lib/prisma";
import { requireAuth } from "@/lib/session";
import { revalidatePath } from "next/cache";
import { z } from "zod";

const schema = z.object({
  targetType: z.enum(["offer", "need", "match"]),
  targetId: z.string().min(1),
  reason: z.string().min(5).max(2000),
});

export async function createReportAction(
  _prev: { error?: string; ok?: boolean } | undefined,
  formData: FormData
): Promise<{ error?: string; ok?: boolean }> {
  const session = await requireAuth();
  const parsed = schema.safeParse({
    targetType: formData.get("targetType"),
    targetId: formData.get("targetId"),
    reason: formData.get("reason"),
  });
  if (!parsed.success) {
    return { error: "请选择举报对象并填写原因（5～2000 字）。" };
  }

  await prisma.report.create({
    data: {
      targetType: parsed.data.targetType,
      targetId: parsed.data.targetId,
      reason: parsed.data.reason,
      createdBy: session.user.id,
    },
  });

  revalidatePath("/admin");
  return { ok: true };
}
