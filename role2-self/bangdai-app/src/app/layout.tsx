import type { Metadata } from "next";
import { Noto_Sans_SC } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/nav";
import { Providers } from "@/components/providers";

const notoSans = Noto_Sans_SC({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "CarryLink 宠物帮带 — 国际航班撮合（演示）",
  description: "旅客携带意向与宠物帮带需求的信息发布与撮合，不提供运输与支付。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className={notoSans.variable}>
      <body className="min-h-screen bg-page font-sans antialiased">
        <Providers>
          <Nav />
          <main className="mx-auto max-w-5xl px-4 pb-16 pt-10 sm:px-6 lg:px-8">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
