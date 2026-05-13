import { test, expect } from "@playwright/test"

test.describe("Smoke — public pages reachable", () => {
  test("home page loads", async ({ page }) => {
    await page.goto("/")
    await expect(page).toHaveTitle(/Indian Stock Analyzer/)
    await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible()
  })

  test("accuracy page loads", async ({ page }) => {
    await page.goto("/accuracy")
    await expect(page).toHaveTitle(/Accuracy/)
  })

  test("subscribe page loads", async ({ page }) => {
    await page.goto("/subscribe")
    await expect(page.getByRole("main")).toBeVisible()
  })

  test("skip-to-main link is present", async ({ page }) => {
    await page.goto("/")
    const skip = page.getByRole("link", { name: /skip to main content/i })
    await expect(skip).toBeAttached()
  })

  test("footer links are present", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByRole("link", { name: "Privacy" })).toBeVisible()
    await expect(page.getByRole("link", { name: "Terms" })).toBeVisible()
  })

  test("nav has no broken links", async ({ page }) => {
    await page.goto("/")
    const navLinks = page.getByRole("navigation").getByRole("link")
    const count = await navLinks.count()
    expect(count).toBeGreaterThan(0)
  })
})

test.describe("a11y — keyboard navigation", () => {
  test("tab order reaches main content", async ({ page }) => {
    await page.goto("/")
    await page.keyboard.press("Tab")
    const focused = await page.evaluate(() => document.activeElement?.tagName)
    expect(["A", "BUTTON"]).toContain(focused)
  })
})
