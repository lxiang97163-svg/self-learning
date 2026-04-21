"use server";

import { prisma } from "@/lib/prisma";
import { requireAuth } from "@/lib/session";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

const createSchema = z.object({
  originCity: z.string().min(1),
  destinationCity: z.string().min(1),
  flightDate: z.string(),
  acceptedSpecies: z.string().min(1),
  maxPetWeightKg: z.coerce.number().positive(),
  carryMode: z.enum(["cabin", "hold", "either"]),
  priceModel: z.enum(["perPet", "fixed"]),
  price: z.coerce.number().nonnegative(),
  currency: z.string().default("CNY"),
  notes: z.string().optional(),
  ackCarrier: z.literal("on"),
});

export async function createPetCarryOfferAction(
  _prev: { error?: string } | undefined,
  formData: FormData
): Promise<{ error?: string }> {
  const session = await requireAuth();
  const parsed = createSchema.safeParse({
    originCity: formData.get("originCity"),
    destinationCity: formData.get("destinationCity"),
    flightDate: formData.get("flightDate"),
    acceptedSpecies: formData.get("acceptedSpecies"),
    maxPetWeightKg: formData.get("maxPetWeightKg"),
    carryMode: formData.get("carryMode"),
    priceModel: formData.get("priceModel"),
    price: formData.get("price"),
    currency: formData.get("currency") || "CNY",
    notes: formData.get("notes") || "",
    ackCarrier: formData.get("ackCarrier"),
  });
  if (!parsed.success) return { error: "请填写完整携带意向并勾选确认。" };

  await prisma.petCarryOffer.create({
    data: {
      ownerId: session.user.id,
      originCity: parsed.data.originCity,
      destinationCity: parsed.data.destinationCity,
      flightDate: new Date(parsed.data.flightDate),
      acceptedSpecies: parsed.data.acceptedSpecies,
      maxPetWeightKg: parsed.data.maxPetWeightKg,
      carryMode: parsed.data.carryMode,
      priceModel: parsed.data.priceModel,
      price: parsed.data.price,
      currency: parsed.data.currency,
      notes: parsed.data.notes?.trim() ?? "",
      status: "open",
    },
  });
  revalidatePath("/offers");
  redirect("/offers");
}
