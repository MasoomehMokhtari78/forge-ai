import { test, expect } from "@playwright/test";

test.describe("Add Repository Dialog & Form Validation", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/repositories");
  });

  test("dialog opens and closes cleanly", async ({ page }) => {
    const newButton = page.getByRole("button", { name: "New" }).first();
    await newButton.click();

    // Verify dialog opened
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(page.getByRole("heading", { name: "Add Repository" })).toBeVisible();
    await expect(page.getByText("Enter a public GitHub repository URL.")).toBeVisible();

    // Close via Cancel button
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).not.toBeVisible();
  });

  test("rejects invalid non-GitHub URL (real backend 422 contract)", async ({ page }) => {
    await page.getByRole("button", { name: "New" }).first().click();

    const input = page.locator("input[placeholder*='github.com']");
    await input.fill("https://gitlab.com/owner/repo");

    const submitBtn = page.getByRole("button", { name: "Add repository" });
    await submitBtn.click();

    // Assert backend 422 error is surfaced
    const alert = page.getByTestId("repo-error-alert");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("Only GitHub (github.com) repositories are supported.");

    // Dialog remains open so user can correct the input
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("handles duplicate repository gracefully (real backend 409 contract)", async ({ page }) => {
    await page.getByRole("button", { name: "New" }).first().click();

    const input = page.locator("input[placeholder*='github.com']");
    await input.fill("https://github.com/github/gitignore");

    const submitBtn = page.getByRole("button", { name: "Add repository" });
    await submitBtn.click();

    // Assert backend 409 conflict error is surfaced with existing repo info
    const alert = page.getByTestId("repo-error-alert");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("already registered");

    // Dialog remains usable
    await expect(submitBtn).toBeEnabled();
  });

  test("recovers from error when user edits the input", async ({ page }) => {
    await page.getByRole("button", { name: "New" }).first().click();

    const input = page.locator("input[placeholder*='github.com']");
    await input.fill("https://gitlab.com/wrong");
    await page.getByRole("button", { name: "Add repository" }).click();

    await expect(page.getByTestId("repo-error-alert")).toBeVisible();

    // Close and reopen resets the form and error state
    await page.getByRole("button", { name: "Cancel" }).click();
    await page.getByRole("button", { name: "New" }).first().click();

    await expect(page.getByTestId("repo-error-alert")).not.toBeVisible();
    await expect(input).toHaveValue("");
  });

  test("prevents double submission by disabling the submit button while pending", async ({ page }) => {
    // Delay backend response by 1.5s to verify button pending / disabled state
    await page.route("http://localhost:8000/repositories", async (route) => {
      if (route.request().method() === "POST") {
        await new Promise((res) => setTimeout(res, 1200));
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Repository already registered" }),
        });
      } else {
        await route.continue();
      }
    });

    await page.getByRole("button", { name: "New" }).first().click();
    const input = page.locator("input[placeholder*='github.com']");
    await input.fill("https://github.com/github/gitignore");

    const submitBtn = page.locator("button[form='add-repo-form']");
    await submitBtn.click();

    // Verify button is disabled and shows pending indicator while submission is in-flight
    await expect(submitBtn).toBeDisabled();
    await expect(submitBtn).toContainText("Adding...");
    await expect(input).toBeDisabled();

    // After response completes, button re-enables with original label
    await expect(submitBtn).toBeEnabled({ timeout: 5000 });
    await expect(submitBtn).toContainText("Add Repository");
  });

  test("handles unexpected server error (500) without crashing", async ({ page }) => {
    // Intercept backend POST /repositories to simulate 500 Internal Server Error
    await page.route("http://localhost:8000/repositories", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Database connection failed unexpectedly" }),
        });
      } else {
        await route.continue();
      }
    });

    await page.getByRole("button", { name: "New" }).first().click();
    const input = page.locator("input[placeholder*='github.com']");
    await input.fill("https://github.com/facebook/react");

    await page.getByRole("button", { name: "Add repository" }).click();

    // Error alert is displayed and app does not crash
    const alert = page.getByTestId("repo-error-alert");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("Database connection failed unexpectedly");
    await expect(page.getByRole("button", { name: "Add repository" })).toBeEnabled();
  });

  test("successful repository creation navigates to workspace and updates UI", async ({ page, request }) => {
    test.setTimeout(60000);
    const targetUrl = "https://github.com/octocat/test-repo1";

    // Pre-flight cleanup: Ensure repo does not already exist from prior interrupted runs
    const reposRes = await request.get("http://localhost:8000/repositories");
    if (reposRes.ok()) {
      const existingRepos = await reposRes.json();
      const existing = existingRepos.find((r: { url: string }) => r.url === targetUrl);
      if (existing) {
        await request.delete(`http://localhost:8000/repositories/${existing.id}`);
      }
    }

    // 1. Submit through the real browser UI
    await page.getByRole("button", { name: "New" }).first().click();
    const input = page.locator("input[placeholder*='github.com']");
    await input.fill(targetUrl);

    // Capture the real POST response to verify it reaches the backend and returns 201
    const [postResponse] = await Promise.all([
      page.waitForResponse((res) => res.url().includes("/repositories") && res.request().method() === "POST"),
      page.locator("button[form='add-repo-form']").click(),
    ]);

    expect(postResponse.status()).toBe(201);
    const postData = await postResponse.json();
    const createdId = postData.id;
    expect(createdId).toBeTruthy();

    try {
      // 2. Dialog closes and browser redirects to /repositories/[createdId]
      await expect(page.getByRole("dialog")).not.toBeVisible();
      await expect(page).toHaveURL(new RegExp(`/repositories/${createdId}`), { timeout: 35000 });

      // 3. Workspace displays repository details loaded by Next.js Server Components from real backend
      await expect(page.locator("h1")).toContainText("test-repo1");
      await expect(page.getByText("octocat/", { exact: true })).toBeVisible();
      await expect(page.getByText(createdId)).toBeVisible();

      // 4. Verify the repository was genuinely persisted in PostgreSQL
      const dbCheck = await request.get(`http://localhost:8000/repositories/${createdId}`);
      expect(dbCheck.status()).toBe(200);
      const persistedRepo = await dbCheck.json();
      expect(persistedRepo.url).toBe(targetUrl);
      expect(persistedRepo.status).toBe("completed");
    } finally {
      // Clean up after test to maintain database isolation
      if (createdId) {
        const deleteRes = await request.delete(`http://localhost:8000/repositories/${createdId}`);
        expect(deleteRes.status()).toBe(204);
      }
    }
  });

  test("automatically triggers indexing when adding a new repository and displays non-zero file/chunk counts", async ({ page, request }) => {
    test.setTimeout(60000);
    // End-to-end verification of automatic indexing with a real, lightweight GitHub repository
    const targetUrl = "https://github.com/octocat/boysenberry-repo-1";

    // Pre-flight cleanup: Ensure target repo is not already present from previous interrupted runs
    const reposRes = await request.get("http://localhost:8000/repositories");
    if (reposRes.ok()) {
      const existingRepos = await reposRes.json();
      const existing = existingRepos.find((r: { url: string }) => r.url === targetUrl);
      if (existing) {
        await request.delete(`http://localhost:8000/repositories/${existing.id}`);
      }
    }

    // 1. Open Add Repository dialog in real browser
    await page.goto("/repositories");
    await page.getByRole("button", { name: "New" }).first().click();

    const input = page.locator("input[placeholder*='github.com']");
    await input.fill(targetUrl);

    // 2. Submit form (sends auto_index: true to backend)
    const submitBtn = page.locator("button[form='add-repo-form']");
    await submitBtn.click();

    // 3. Verify submit button transitions to disabled state
    await expect(submitBtn).toBeDisabled();

    // 4. Verify navigation to the new workspace page (allow time for git clone + embedding generation)
    await expect(page).toHaveURL(/\/repositories\/[0-9a-f-]{36}/, { timeout: 35000 });
    await expect(page.getByRole("dialog")).not.toBeVisible();

    // Extract the created repository ID from the active URL
    const createdRepoId = page.url().split("/").pop();
    expect(createdRepoId).toBeTruthy();

    try {
      // 5. Verify workspace displays repository details
      await expect(page.locator("h1")).toContainText("boysenberry-repo-1");
      await expect(page.getByText("octocat/", { exact: true })).toBeVisible();

      // 6. Verify Index card is visible and contains non-zero counts
      const indexCard = page.locator("div.rounded-lg:has(span:text-is('Index'))");
      await expect(indexCard).toBeVisible();
      await expect(indexCard.getByText("Files", { exact: true })).toBeVisible();
      await expect(indexCard.getByText("Chunks", { exact: true })).toBeVisible();

      // Locate the tabular count values within the Index card
      const countValues = indexCard.locator("span.tabular-nums");
      
      // Automatic indexing must result in > 0 files and > 0 chunks
      await expect(countValues.first()).not.toHaveText("0", { timeout: 10000 });
      await expect(countValues.last()).not.toHaveText("0", { timeout: 10000 });
    } finally {
      // 7. Cleanup via HTTP DELETE to leave the test database idempotent and clean
      if (createdRepoId) {
        const deleteRes = await request.delete(`http://localhost:8000/repositories/${createdRepoId}`);
        expect(deleteRes.status()).toBe(204);
      }
    }
  });
});
