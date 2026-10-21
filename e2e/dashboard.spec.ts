import { expect, test } from "@playwright/test";

const TRENDS = {
  k_threshold: 20,
  rows: [
    {
      cluster_code: "CRP-01",
      move_id: 2,
      iso_week: "2026-W45",
      n_teachers: 24,
      avg_improvement: 2.1,
      avg_sessions: 3.4,
    },
  ],
};

test("connection card is shown first", async ({ page }) => {
  await page.goto("http://127.0.0.1:8124/");
  await expect(page.getByRole("button", { name: /show trends/i })).toBeVisible();
});

test("a wrong token shows the rejected message", async ({ page }) => {
  await page.route("**/dashboard/trends", async (route) => {
    await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "nope" }) });
  });
  await page.goto("http://127.0.0.1:8124/");
  await page.waitForLoadState("networkidle");
  const allInputs = page.locator("form input");
  await allInputs.nth(0).fill("http://127.0.0.1:9999");
  await allInputs.nth(1).fill("bad-token");
  await page.getByRole("button", { name: /show trends/i }).click();
  await expect(page.locator(".badge.error")).toBeVisible({ timeout: 15000 });
});

test("suppressed cells render as Suppressed < 20", async ({ page }) => {
  await page.route("**/dashboard/trends", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TRENDS) });
  });
  await page.goto("http://127.0.0.1:8124/");
  await page.waitForLoadState("networkidle");
  const allInputs = page.locator("form input");
  await allInputs.nth(0).fill("http://127.0.0.1:9999");
  await allInputs.nth(1).fill("good-token");
  await page.getByRole("button", { name: /show trends/i }).click();
  await expect(page.getByText(/Suppressed.*< 20/).first()).toBeVisible();
  await expect(page.getByText("2.10")).toBeVisible();
});