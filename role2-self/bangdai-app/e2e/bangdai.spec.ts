import { test, expect } from "@playwright/test";

function uniq(prefix: string) {
  return `${prefix}_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
}

test.describe("宠物帮带演示闭环", () => {
  test("注册 → 携带意向/需求 → 兴趣 → 接受 → 消息 → 金额 → 完成", async ({ page, context }) => {
    const pass = "TestPass123!";
    const emailA = uniq("a") + "@example.com";
    const emailB = uniq("b") + "@example.com";

    // --- User A: register + offer
    await page.goto("/auth/register");
    await page.getByTestId("register-displayName").fill("携带方甲");
    await page.getByTestId("register-email").fill(emailA);
    await page.getByTestId("register-password").fill(pass);
    await page.getByTestId("ack-traveler").check();
    await page.getByTestId("ack-requester").check();
    await page.getByTestId("ack-prohibited").check();
    await page.getByRole("button", { name: "注册" }).click();
    await expect(page).toHaveURL(/\/auth\/login/);

    await page.getByTestId("login-email").fill(emailA);
    await page.getByTestId("login-password").fill(pass);
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL(/\/offers/);

    await page.goto("/offers/new");
    await page.getByTestId("offer-origin").fill("上海");
    await page.getByTestId("offer-dest").fill("东京");
    const today = new Date();
    const iso = today.toISOString().slice(0, 10);
    await page.getByTestId("offer-date").fill(iso);
    await page.getByTestId("offer-species").fill("猫");
    await page.getByTestId("offer-maxkg").fill("8");
    await page.getByTestId("offer-price").fill("800");
    await page.locator('input[name="ackCarrier"]').check();
    await page.getByTestId("offer-submit").click();
    await expect(page).toHaveURL(/\/offers$/);

    await page.goto("/offers");
    await page.locator("main ul li a").filter({ hasText: "上海" }).first().click();
    const offerUrl = page.url();

    // --- User B: register + need + express interest
    await context.clearCookies();
    await page.goto("/auth/register");
    await page.getByTestId("register-displayName").fill("需求乙");
    await page.getByTestId("register-email").fill(emailB);
    await page.getByTestId("register-password").fill(pass);
    await page.getByTestId("ack-traveler").check();
    await page.getByTestId("ack-requester").check();
    await page.getByTestId("ack-prohibited").check();
    await page.getByRole("button", { name: "注册" }).click();
    await expect(page).toHaveURL(/\/auth\/login/);

    await page.getByTestId("login-email").fill(emailB);
    await page.getByTestId("login-password").fill(pass);
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL(/\/offers/);

    await page.goto("/needs/new");
    await page.getByTestId("need-dest").fill("东京");
    await page.getByTestId("need-date").fill(iso);
    await page.getByTestId("need-species").fill("猫");
    await page.getByTestId("need-weight").fill("5");
    await page.getByTestId("need-notes").fill("健康猫，已免疫，需随行协助");
    await page.getByTestId("need-budget-min").fill("500");
    await page.getByTestId("need-budget-max").fill("1500");
    await page.locator('input[name="ackNeed"]').check();
    await page.getByTestId("need-submit").click();
    await expect(page).toHaveURL(/\/needs$/);

    await page.goto(offerUrl);
    await page.getByTestId("express-interest").click();
    await expect(page).toHaveURL(/\/matches\//);

    const matchUrl = page.url();

    // --- User A: accept
    await context.clearCookies();
    await page.goto("/auth/login");
    await page.getByTestId("login-email").fill(emailA);
    await page.getByTestId("login-password").fill(pass);
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL(/\/offers/);

    await page.goto(matchUrl);
    await page.getByRole("button", { name: "接受" }).click();
    await expect(page.getByText("状态：accepted")).toBeVisible();

    // --- messages
    await page.getByTestId("open-messages").click();
    await expect(page).toHaveURL(/\/messages\//);
    await page.getByTestId("message-body").fill("站内沟通测试：线下交割时间另约。");
    await page.getByTestId("send-message").click();
    await expect(page.getByText("站内沟通测试")).toBeVisible();

    // --- agreed amount + complete
    await page.goto(matchUrl);
    await page.getByTestId("agreed-amount").fill("200");
    await page.getByTestId("save-amount").click();
    await expect(page.getByText("约定金额：200")).toBeVisible();

    await page.getByTestId("complete-delivery").click();
    await expect(page.getByText("状态：completed")).toBeVisible();
  });
});
