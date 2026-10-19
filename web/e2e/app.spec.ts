import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

test("live page plays the demo match", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "No game yet" })).toBeVisible();
  await page.getByRole("button", { name: "Play a demo match" }).click();
  await expect(page.getByText("Demo match, made-up numbers")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Juggernaut" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByLabel("Upcoming timers")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Next items" })).toBeVisible();
  await expect(page.getByText("Receiving game data").or(page.getByText("Playing demo"))).toBeVisible();
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByRole("heading", { name: "No game yet" })).toBeVisible({ timeout: 10_000 });
});

test("draft by keyboard gives suggestions and a win estimate", async ({ page }) => {
  await page.goto("/draft");
  const search = page.getByLabel("Search heroes");
  for (const hero of ["pa", "lion", "invo"]) {
    await search.fill(hero);
    await search.press("Enter");
  }
  await search.press("Tab");
  for (const hero of ["cm", "axe"]) {
    await search.fill(hero);
    await search.press("Enter");
  }
  await expect(page.getByLabel("radiant picks").getByText("Crystal Maiden")).toBeVisible();
  await expect(page.getByLabel("dire picks").getByText("Phantom Assassin")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Picks for you" })).toBeVisible();
  await expect(page.getByLabel("Win probability")).toBeVisible();
  await expect(page.locator("table.suggest tbody tr")).toHaveCount(15);
  await page.getByRole("tab", { name: "Pos 5" }).click();
  await expect(page.locator("table.suggest tbody tr").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Items to plan for against their draft" })).toBeVisible();
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(page.getByLabel("dire picks").getByText("Phantom Assassin")).toHaveCount(0);
});

test("hero page shows a pro build", async ({ page }) => {
  await page.goto("/heroes");
  await page.getByLabel("Search heroes").fill("jugg");
  await page.getByRole("link", { name: "Juggernaut" }).click();
  await expect(page.getByRole("heading", { name: "Juggernaut", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Core items, in the order pros finish them" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Skill order" })).toBeVisible();
  await page.getByRole("tab", { name: "Matchups" }).click();
  await expect(page.getByRole("heading", { name: "Countered by" })).toBeVisible();
});

test("meta, items and setup load", async ({ page }) => {
  await page.goto("/meta");
  await expect(page.locator("tbody tr").first()).toBeVisible();
  expect(await page.locator("tbody tr").count()).toBeGreaterThan(50);
  await page.goto("/items/black_king_bar");
  await expect(page.getByRole("heading", { name: "Black King Bar" })).toBeVisible();
  await page.goto("/setup");
  await expect(page.getByRole("heading", { name: "Connect Dota 2" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Data", exact: true })).toBeVisible();
});

test("settings switch the theme", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("keyboard shortcuts switch pages", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("2");
  await expect(page).toHaveURL(/\/draft$/);
  await page.keyboard.press("5");
  await expect(page).toHaveURL(/\/meta$/);
});
