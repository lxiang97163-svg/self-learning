"use server";

import bcrypt from "bcryptjs";
import { prisma } from "@/lib/prisma";
import { redirect } from "next/navigation";
import { z } from "zod";

const registerSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  displayName: z.string().min(1).max(64),
  ackTraveler: z.literal("on"),
  ackRequester: z.literal("on"),
  ackProhibited: z.literal("on"),
});

export async function registerAction(
  _prev: { error?: string } | undefined,
  formData: FormData
): Promise<{ error?: string }> {
  const parsed = registerSchema.safeParse({
    email: formData.get("email"),
    password: formData.get("password"),
    displayName: formData.get("displayName"),
    ackTraveler: formData.get("ackTraveler"),
    ackRequester: formData.get("ackRequester"),
    ackProhibited: formData.get("ackProhibited"),
  });

  if (!parsed.success) {
    return { error: "请检查表单：邮箱、密码（至少 8 位）及全部确认项。" };
  }

  const exists = await prisma.user.findUnique({ where: { email: parsed.data.email } });
  if (exists) {
    return { error: "该邮箱已注册。" };
  }

  const passwordHash = await bcrypt.hash(parsed.data.password, 12);
  await prisma.user.create({
    data: {
      email: parsed.data.email,
      passwordHash,
      displayName: parsed.data.displayName,
    },
  });

  redirect("/auth/login?registered=1");
}
