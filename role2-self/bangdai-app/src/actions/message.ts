"use server";

import { prisma } from "@/lib/prisma";
import { requireAuth } from "@/lib/session";
import { revalidatePath } from "next/cache";

export async function sendMessageAction(_prev: unknown, formData: FormData) {
  const session = await requireAuth();
  const threadId = String(formData.get("threadId") || "");
  const body = String(formData.get("body") || "").trim();
  if (!threadId || !body) return { error: "请输入内容。" };

  const m = await prisma.petCarryMatch.findUnique({
    where: { id: threadId },
    include: { offer: true, need: true },
  });
  if (!m) return { error: "会话不存在。" };
  if (m.status !== "accepted") {
    return { error: "仅「已接受」且未完成交割前可发消息。" };
  }

  const uid = session.user.id;
  if (uid !== m.offer.ownerId && uid !== m.need.ownerId) return { error: "无权发消息。" };

  await prisma.message.create({
    data: {
      threadId,
      senderId: uid,
      body,
    },
  });

  revalidatePath(`/messages/${threadId}`);
  revalidatePath("/messages");
  return { ok: true };
}
