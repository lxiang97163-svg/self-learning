"use server";

import { prisma } from "@/lib/prisma";
import { requireAuth } from "@/lib/session";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

const createSchema = z.object({
  originCity: z.string().optional(),
  destinationCity: z.string().min(1),
  neededByDate: z.string(),
  petSpecies: z.string().min(1),
  petWeightKg: z.coerce.number().positive(),
  petNotes: z.string().min(1),
  budgetMin: z.coerce.number().nonnegative(),
  budgetMax: z.coerce.number().nonnegative(),
  currency: z.string().default("CNY"),
  ackNeed: z.literal("on"),
});

export async function createPetCarryNeedAction(
  _prev: { error?: string } | undefined,
  formData: FormData
): Promise<{ error?: string }> {
  const session = await requireAuth();
  const parsed = createSchema.safeParse({
    originCity: formData.get("originCity") || "",
    destinationCity: formData.get("destinationCity"),
    neededByDate: formData.get("neededByDate"),
    petSpecies: formData.get("petSpecies"),
    petWeightKg: formData.get("petWeightKg"),
    petNotes: formData.get("petNotes"),
    budgetMin: formData.get("budgetMin"),
    budgetMax: formData.get("budgetMax"),
    currency: formData.get("currency") || "CNY",
    ackNeed: formData.get("ackNeed"),
  });
  if (!parsed.success) return { error: "请填写完整宠物帮带需求并勾选确认。" };
  if (parsed.data.budgetMax < parsed.data.budgetMin) {
    return { error: "预算上限应不小于下限。" };
  }

  await prisma.petCarryNeed.create({
    data: {
      ownerId: session.user.id,
      originCity: parsed.data.originCity?.trim() ?? "",
      destinationCity: parsed.data.destinationCity,
      neededByDate: new Date(parsed.data.neededByDate),
      petSpecies: parsed.data.petSpecies,
      petWeightKg: parsed.data.petWeightKg,
      petNotes: parsed.data.petNotes,
      budgetMin: parsed.data.budgetMin,
      budgetMax: parsed.data.budgetMax,
      currency: parsed.data.currency,
      status: "open",
    },
  });
  revalidatePath("/needs");
  redirect("/needs");
}
