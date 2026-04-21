"use server";

import { prisma } from "@/lib/prisma";
import { computePlatformFee } from "@/lib/fee";
import { requireAuth } from "@/lib/session";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

function counterpartyId(offerOwnerId: string, needOwnerId: string, fromUserId: string) {
  return fromUserId === offerOwnerId ? needOwnerId : offerOwnerId;
}

export async function createInterestAction(
  _prev: { error?: string } | undefined,
  formData: FormData
): Promise<{ error?: string }> {
  const session = await requireAuth();
  const offerId = String(formData.get("offerId") || "");
  const needId = String(formData.get("needId") || "");
  if (!offerId || !needId) return { error: "缺少携带意向或需求。" };

  const offer = await prisma.petCarryOffer.findUnique({ where: { id: offerId } });
  const need = await prisma.petCarryNeed.findUnique({ where: { id: needId } });
  if (!offer || !need) return { error: "携带意向或需求不存在。" };
  if (offer.ownerId === need.ownerId) return { error: "不能匹配自己的携带意向与需求。" };
  const uid = session.user.id;
  if (uid !== offer.ownerId && uid !== need.ownerId) return { error: "无权发起该匹配。" };
  if (offer.destinationCity.trim() !== need.destinationCity.trim()) {
    return { error: "目的地城市需与需求一致。" };
  }
  if (need.petWeightKg > offer.maxPetWeightKg) {
    return { error: "宠物体重超过该携带意向声明的上限。" };
  }
  if (offer.status !== "open" || need.status !== "open") {
    return { error: "携带意向或需求已不可用。" };
  }

  const existing = await prisma.petCarryMatch.findUnique({
    where: {
      offerId_needId: { offerId: offer.id, needId: need.id },
    },
  });
  if (existing) {
    revalidatePath(`/matches/${existing.id}`);
    redirect(`/matches/${existing.id}`);
  }

  const created = await prisma.petCarryMatch.create({
    data: {
      offerId: offer.id,
      needId: need.id,
      fromUserId: uid,
      status: "pending",
    },
  });

  revalidatePath(`/offers/${offer.id}`);
  revalidatePath(`/needs/${need.id}`);
  revalidatePath("/messages");
  redirect(`/matches/${created.id}`);
}

export async function acceptInterestAction(
  _prev: { error?: string } | undefined,
  formData: FormData
): Promise<{ error?: string }> {
  const session = await requireAuth();
  const id = String(formData.get("matchId") || "");
  if (!id) return { error: "缺少撮合单。" };

  const m = await prisma.petCarryMatch.findUnique({
    where: { id },
    include: { offer: true, need: true },
  });
  if (!m || m.status !== "pending") return { error: "状态不可接受。" };

  const cp = counterpartyId(m.offer.ownerId, m.need.ownerId, m.fromUserId);
  if (session.user.id !== cp) return { error: "仅对方可接受。" };

  await prisma.$transaction([
    prisma.petCarryMatch.update({
      where: { id: m.id },
      data: { status: "accepted" },
    }),
    prisma.petCarryOffer.update({
      where: { id: m.offerId },
      data: { status: "full" },
    }),
    prisma.petCarryNeed.update({
      where: { id: m.needId },
      data: { status: "matched" },
    }),
  ]);

  revalidatePath(`/matches/${m.id}`);
  revalidatePath("/messages");
  redirect(`/matches/${m.id}`);
}

export async function rejectInterestAction(
  _prev: { error?: string } | undefined,
  formData: FormData
): Promise<{ error?: string }> {
  const session = await requireAuth();
  const id = String(formData.get("matchId") || "");
  if (!id) return { error: "缺少撮合单。" };

  const m = await prisma.petCarryMatch.findUnique({
    where: { id },
    include: { offer: true, need: true },
  });
  if (!m || m.status !== "pending") return { error: "状态不可拒绝。" };

  const cp = counterpartyId(m.offer.ownerId, m.need.ownerId, m.fromUserId);
  if (session.user.id !== cp) return { error: "仅对方可拒绝。" };

  await prisma.petCarryMatch.update({
    where: { id: m.id },
    data: { status: "rejected" },
  });
  revalidatePath(`/matches/${m.id}`);
  redirect(`/matches/${m.id}`);
}

const amountSchema = z.object({
  matchId: z.string(),
  agreedAmount: z.coerce.number().positive(),
});

export async function saveAgreedAmountAction(
  _prev: { error?: string; ok?: boolean } | undefined,
  formData: FormData
): Promise<{ error?: string; ok?: boolean }> {
  const session = await requireAuth();
  const parsed = amountSchema.safeParse({
    matchId: formData.get("matchId"),
    agreedAmount: formData.get("agreedAmount"),
  });
  if (!parsed.success) return { error: "请输入有效的约定金额。" };

  const m = await prisma.petCarryMatch.findUnique({
    where: { id: parsed.data.matchId },
    include: { offer: true, need: true },
  });
  if (!m || m.status !== "accepted") return { error: "仅已接受的撮合可记录金额。" };

  const uid = session.user.id;
  if (uid !== m.offer.ownerId && uid !== m.need.ownerId) return { error: "无权操作。" };

  const { platformFeeRate, platformFeeAmount } = computePlatformFee(parsed.data.agreedAmount);

  await prisma.commissionRecord.upsert({
    where: { petCarryMatchId: m.id },
    create: {
      petCarryMatchId: m.id,
      agreedAmount: parsed.data.agreedAmount,
      platformFeeRate,
      platformFeeAmount,
      status: "recorded",
    },
    update: {
      agreedAmount: parsed.data.agreedAmount,
      platformFeeRate,
      platformFeeAmount,
    },
  });

  revalidatePath(`/matches/${m.id}`);
  return { ok: true };
}

export async function completeDeliveryAction(
  _prev: { error?: string; ok?: boolean } | undefined,
  formData: FormData
): Promise<{ error?: string; ok?: boolean }> {
  const session = await requireAuth();
  const id = String(formData.get("matchId") || "");
  if (!id) return { error: "缺少撮合单。" };

  const m = await prisma.petCarryMatch.findUnique({
    where: { id },
    include: { offer: true, need: true, commission: true },
  });
  if (!m || m.status !== "accepted") return { error: "当前状态不可完成。" };

  const uid = session.user.id;
  if (uid !== m.offer.ownerId && uid !== m.need.ownerId) return { error: "无权操作。" };
  if (!m.commission) return { error: "请先记录约定金额。" };

  await prisma.petCarryMatch.update({
    where: { id: m.id },
    data: { status: "completed" },
  });

  revalidatePath(`/matches/${m.id}`);
  return { ok: true };
}
