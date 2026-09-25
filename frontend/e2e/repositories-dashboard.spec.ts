import { test, expect } from "@playwright/test";

test.describe("Repository Dashboard", () => {
  test("root URL redirects to /repositories", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/repositories/);
  });

  test("renders application shell with navigation and sidebar", async ({ page }) => {
    await page.goto("/repositories");

    // Branding and header
    await expect(page.getByText("ForgeAI").first()).toBeVisible();
    await expect(page.getByText("Local").first()).toBeVisible();

    // Sidebar items
    const sidebar = page.locator("aside, [data-slot='sidebar']");
    await expect(sidebar.getByText("Repositories").first()).toBeVisible();
    await expect(sidebar.getByText("Settings")).toBeVisible();
  });

  test("loads and renders repositories from the backend", async ({ page }) => {
    await page.goto("/repositories");

    // Page title and count
    await expect(page.getByRole("heading", { name: "Repositories", exact: true })).toBeVisible();
    await expect(page.locator("text=/\\d+ repositories/")).toBeVisible();

    // Known seeded repositories in DB
    await expect(page.getByText("gitignore").first()).toBeVisible();
    await expect(page.getByText("Spoon-Knife").first()).toBeVisible();
    await expect(page.getByText("Hello-World").first()).toBeVisible();

    // Status badges match backend data
    await expect(page.locator("span:has-text('Indexed')").first()).toBeVisible();
    await expect(page.locator("span:has-text('Failed')").first()).toBeVisible();

    // Failed repositories display meaningful failure message
    await expect(
      page.getByText("Git is not installed or available on the server.").or(
        page.getByText("Failed to initiate repository clone.")
      ).first()
    ).toBeVisible();
  });

  test("renders empty state when there are no repositories", async ({ page }) => {
    await page.goto("/repositories?state=empty");

    await expect(page.getByRole("heading", { name: "No repositories yet" })).toBeVisible();
    await expect(
      page.getByText("Connect a public GitHub repository to start understanding your codebase with ForgeAI.")
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "New" }).first()).toBeVisible();
  });

  test("renders resilient error state when repository API fails", async ({ page }) => {
    await page.goto("/repositories?state=error");

    await expect(page.getByRole("heading", { name: "Failed to load repositories" })).toBeVisible();
    await expect(
      page.getByText("Could not connect to ForgeAI backend. Please check that the server is running.")
    ).toBeVisible();

    // Application shell and sidebar navigation remain interactive and intact
    await expect(page.getByText("ForgeAI").first()).toBeVisible();
    await expect(page.getByText("Settings")).toBeVisible();
  });
});
