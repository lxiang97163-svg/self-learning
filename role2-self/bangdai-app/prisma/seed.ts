import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const prisma = new PrismaClient();

async function main() {
  const email = process.env.SEED_ADMIN_EMAIL || "admin@example.com";
  const plain = process.env.SEED_ADMIN_PASSWORD || "ChangeMe_Strong!";
  const hash = await bcrypt.hash(plain, 12);

  await prisma.user.upsert({
    where: { email },
    create: {
      email,
      passwordHash: hash,
      role: "admin",
      displayName: "系统管理员",
    },
    update: {
      role: "admin",
      passwordHash: hash,
    },
  });

  console.log("Seed OK: admin user", email);
}

main()
  .then(() => prisma.$disconnect())
  .catch((e) => {
    console.error(e);
    prisma.$disconnect();
    process.exit(1);
  });
