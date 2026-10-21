import { expect, test } from "@playwright/test";

// The web room posts to {apiBase}/web/turn with X-Demo-Code. We intercept that call and
// return a canned reply, so no backend or demo code is needed.

const FAKE_REPLY = {
  text: "रिया: मैंने 52 में से 17 घटाया, जवाब 45।",
  lang: "hi",
  audio_base64: null,
  audio_mime: null,
  refused: false,
};

test("gate rejects a malformed code", async ({ page }) => {
  await page.goto("/");
  await page.fill("#code", "short");
  await page.click("#start");
  await expect(page.locator("#gate-error")).toBeVisible();
});

test("a valid code opens the session and shows the welcome bubble", async ({ page }) => {
  await page.goto("/");
  await page.fill("#code", "A".repeat(22));
  await page.click("#start");
  await expect(page.locator("#session")).toBeVisible();
  await expect(page.locator(".bubble.anviq").first()).toBeVisible();
});

test("typing a line shows the reply", async ({ page }) => {
  await page.goto("/");
  await page.fill("#code", "A".repeat(22));
  await page.click("#start");
  await expect(page.locator("#session")).toBeVisible();
  await page.route("**/web/turn", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(FAKE_REPLY) });
  });
  await page.locator("details.typed summary").click();
  await page.fill("#text", "Namaste");
  await page.click("#send-text");
  await expect(page.locator(".bubble.anviq").last()).toContainText("रिया");
});

test("a refused reply is styled distinctly", async ({ page }) => {
  await page.route("**/web/turn", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...FAKE_REPLY, refused: true }),
    });
  });
  await page.goto("/");
  await page.fill("#code", "A".repeat(22));
  await page.click("#start");
  await page.waitForSelector("#session:not([hidden])", { timeout: 5000 });
  await page.locator("details.typed summary").click();
  await page.fill("#text", "Namaste");
  await page.click("#send-text");
  await expect(page.locator(".bubble.refused")).toBeVisible();
});

test("a 401 shows the single refused message", async ({ page }) => {
  await page.route("**/web/turn", async (route) => {
    await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "nope" }) });
  });
  await page.goto("/");
  await page.fill("#code", "A".repeat(22));
  await page.click("#start");
  await page.waitForSelector("#session:not([hidden])", { timeout: 5000 });
  await page.locator("details.typed summary").click();
  await page.fill("#text", "Namaste");
  await page.click("#send-text");
  await expect(page.locator("#turn-status")).toHaveClass(/error/);
});