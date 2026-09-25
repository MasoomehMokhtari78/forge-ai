import { test, expect } from "@playwright/test";

test.describe("Repository Workspace", () => {
  const realRepoId = "09f06d60-9b91-469f-b8b8-9a045526af21";

  test("loads and renders valid repository workspace with real backend data", async ({ page }) => {
    await page.goto(`/repositories/${realRepoId}`);

    // Workspace topbar breadcrumbs
    await expect(page.getByText("github/", { exact: true })).toBeVisible();
    await expect(page.getByText("gitignore").first()).toBeVisible();
    await expect(page.locator("span:has-text('Indexed')").first()).toBeVisible();

    // Main workspace content
    await expect(page.locator("h1")).toContainText("gitignore");
    await expect(page.getByText("github.com/github/gitignore")).toBeVisible();
    await expect(page.getByText(realRepoId)).toBeVisible();

    // Index statistics (real data: 316 files, 413 chunks)
    await expect(page.getByText("316")).toBeVisible();
    await expect(page.getByText("413")).toBeVisible();

    // Workspace panels
    await expect(page.getByText("File browser coming in the next phase.")).toBeVisible();
    await expect(page.getByText("AI Assistant", { exact: false })).toBeVisible();
  });

  test("navigates back to repositories list from workspace breadcrumb", async ({ page }) => {
    await page.goto(`/repositories/${realRepoId}`);

    const backLink = page.getByRole("link", { name: "Repositories" }).first();
    await backLink.click();

    await expect(page).toHaveURL(/\/repositories$/);
    await expect(page.getByRole("heading", { name: "Repositories" })).toBeVisible();
  });

  test("renders custom 404 page for nonexistent repository ID", async ({ page }) => {
    await page.goto("/repositories/00000000-0000-0000-0000-000000000000");

    await expect(page.getByRole("heading", { name: "Repository not found" })).toBeVisible();
    await expect(page.getByText("This repository does not exist or may have been removed.")).toBeVisible();

    const backButton = page.getByRole("link", { name: "Back to Repositories" });
    await expect(backButton).toBeVisible();
    await backButton.click();
    await expect(page).toHaveURL(/\/repositories$/);
  });
});
