import { test, expect } from "@playwright/test";

test.describe("Repository Workspace - Semantic Search Vertical Slice", () => {
  const completedRepoId = "8962366c-b33a-49d9-a4e0-919384c6665b"; // MasoomehMokhtari78/Portfolio (indexed)
  const failedRepoId = "4c844aed-5822-43f7-bf42-e53fcb2335c9"; // octocat/Spoon-Knife (failed / unindexed)

  test("search UI is visible in the repository workspace", async ({ page }) => {
    await page.goto(`/repositories/${completedRepoId}?tab=search`);

    // Verify search panel and primary interactive elements are visible
    const searchPanel = page.getByTestId("semantic-search-panel");
    await expect(searchPanel).toBeVisible();

    const searchInput = page.getByTestId("semantic-search-input");
    await expect(searchInput).toBeVisible();
    await expect(searchInput).toBeEnabled();

    const searchButton = page.getByTestId("semantic-search-button");
    await expect(searchButton).toBeVisible();

    // Verify topbar search shortcut trigger is present
    const topbarSearchTrigger = page.getByTestId("workspace-search-trigger");
    await expect(topbarSearchTrigger).toBeVisible();
  });

  test("rejects empty or whitespace query on the client side", async ({ page }) => {
    await page.goto(`/repositories/${completedRepoId}?tab=search`);

    const searchInput = page.getByTestId("semantic-search-input");
    const searchButton = page.getByTestId("semantic-search-button");

    // Click search with empty input
    await searchButton.click();

    // Client-side validation message must be displayed
    const validationError = page.getByTestId("search-validation-error");
    await expect(validationError).toBeVisible();
    await expect(validationError).toContainText("Please enter a search query.");

    // Fill with whitespace and submit via Enter
    await searchInput.fill("   ");
    await searchInput.press("Enter");
    await expect(validationError).toBeVisible();

    // Results container should not be present
    await expect(page.getByTestId("semantic-search-results")).not.toBeVisible();
  });

  test("performs real semantic search with pgvector retrieval and displays ranked results", async ({
    page,
  }) => {
    test.setTimeout(60000);
    await page.goto(`/repositories/${completedRepoId}?tab=search`);

    const searchInput = page.getByTestId("semantic-search-input");
    const searchButton = page.getByTestId("semantic-search-button");

    // Enter a natural language semantic query
    await searchInput.fill("portfolio layout and project showcase");

    // Submit search and wait for real backend pgvector search response
    const searchResponsePromise = page.waitForResponse(
      (resp) =>
        resp.url().includes(`/repositories/${completedRepoId}/search`) &&
        resp.status() === 200,
      { timeout: 45000 }
    );

    await searchButton.click();

    const searchResponse = await searchResponsePromise;
    expect(searchResponse.ok()).toBeTruthy();

    const responseJson = await searchResponse.json();
    expect(responseJson.results.length).toBeGreaterThan(0);

    // Results list must render with result items
    const resultsContainer = page.getByTestId("semantic-search-results");
    await expect(resultsContainer).toBeVisible();

    // Verify first result item structure: file path, line range, similarity badge, code snippet
    const firstItem = page.getByTestId("search-result-item-0");
    await expect(firstItem).toBeVisible();

    // Must display line range
    await expect(firstItem).toContainText("Lines ");

    // Must display similarity match badge
    await expect(firstItem.getByText(/% match/)).toBeVisible();

    // Must display code snippet block
    const codeSnippet = firstItem.locator("pre code");
    await expect(codeSnippet).toBeVisible();
    const snippetText = await codeSnippet.textContent();
    expect(snippetText).toBeTruthy();
    expect(snippetText!.length).toBeGreaterThan(10);
  });

  test("clicking a search result opens the file in the code viewer with line deep-linking", async ({
    page,
  }) => {
    test.setTimeout(60000);
    await page.goto(`/repositories/${completedRepoId}?tab=search`);

    const searchInput = page.getByTestId("semantic-search-input");
    await searchInput.fill("portfolio layout and project showcase");

    const searchResponsePromise = page.waitForResponse(
      (resp) =>
        resp.url().includes(`/repositories/${completedRepoId}/search`) &&
        resp.status() === 200,
      { timeout: 45000 }
    );
    await searchInput.press("Enter");
    await searchResponsePromise;

    // First result item
    const firstItem = page.getByTestId("search-result-item-0");
    await expect(firstItem).toBeVisible();

    // Click "Open in viewer"
    const openButton = page.getByTestId("open-result-button-0");
    await openButton.click();

    // URL should be updated with ?file=... and &line=... (preserving any existing tab param)
    await expect(page).toHaveURL(/[?&]file=.+&line=\d+/);

    // Code viewer must be rendered
    const codeViewer = page.getByTestId("code-viewer");
    await expect(codeViewer).toBeVisible();

    // Gutter should highlight the target line
    const highlightedLine = page.locator('[data-highlighted-line="true"]');
    await expect(highlightedLine).toBeVisible();

    // Target line badge should be visible in code viewer header
    const targetLineBadge = page.getByTestId("target-line-badge");
    await expect(targetLineBadge).toBeVisible();
    await expect(targetLineBadge).toContainText("Line ");
  });

  test("displays empty state when query returns no relevant code chunks", async ({
    page,
  }) => {
    await page.goto(`/repositories/${completedRepoId}?tab=search`);

    // Intercept search endpoint to simulate zero results
    await page.route(`**/repositories/${completedRepoId}/search`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          repository_id: completedRepoId,
          query: "completely unrelated obscure topic",
          results: [],
        }),
      });
    });

    const searchInput = page.getByTestId("semantic-search-input");
    await searchInput.fill("completely unrelated obscure topic");
    await searchInput.press("Enter");

    // Empty state container must be displayed
    const noResults = page.getByTestId("search-no-results");
    await expect(noResults).toBeVisible();
    await expect(noResults).toContainText("No relevant code found in this repository.");
  });

  test("handles backend search error gracefully with retry capability", async ({
    page,
  }) => {
    await page.goto(`/repositories/${completedRepoId}?tab=search`);

    let shouldFail = true;
    await page.route(`**/repositories/${completedRepoId}/search`, async (route) => {
      if (shouldFail) {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Internal vector database query error" }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            repository_id: completedRepoId,
            query: "test retry",
            results: [
              {
                chunk_id: "c1",
                file_id: "f1",
                path: "src/index.ts",
                content: "export const ok = true;",
                start_line: 1,
                end_line: 5,
                similarity: 0.95,
              },
            ],
          }),
        });
      }
    });

    const searchInput = page.getByTestId("semantic-search-input");
    await searchInput.fill("test retry");
    await searchInput.press("Enter");

    // Error state must be visible
    const errorState = page.getByTestId("search-error");
    await expect(errorState).toBeVisible();
    await expect(errorState).toContainText("Internal vector database query error");

    // Retry button should be available
    const retryButton = page.getByTestId("search-retry-button");
    await expect(retryButton).toBeVisible();

    // Click retry with recovered backend
    shouldFail = false;
    await retryButton.click();

    // Results should now load successfully
    const resultsContainer = page.getByTestId("semantic-search-results");
    await expect(resultsContainer).toBeVisible();
    await expect(page.getByTestId("search-result-item-0")).toBeVisible();
  });

  test("renders disabled not-indexed state for unindexed repository", async ({
    page,
  }) => {
    await page.goto(`/repositories/${failedRepoId}?tab=search`);

    // Verify search panel renders not-indexed state
    const notIndexedState = page.getByTestId("search-not-indexed");
    await expect(notIndexedState).toBeVisible();
    await expect(notIndexedState).toContainText("This repository has not been indexed yet.");

    // Search input should be disabled
    const searchInput = page.getByTestId("semantic-search-input");
    await expect(searchInput).toBeDisabled();
  });

  test("supports keyboard shortcut Cmd/Ctrl+K and topbar trigger to focus search input", async ({
    page,
  }) => {
    await page.goto(`/repositories/${completedRepoId}?tab=search`);

    const searchInput = page.getByTestId("semantic-search-input");

    // Ensure input is not focused initially
    await page.locator("body").click();
    await expect(searchInput).not.toBeFocused();

    // Trigger via topbar button
    const topbarTrigger = page.getByTestId("workspace-search-trigger");
    await topbarTrigger.click();
    await expect(searchInput).toBeFocused();

    // Blur and trigger via keyboard shortcut
    await page.locator("body").click();
    await expect(searchInput).not.toBeFocused();

    await page.keyboard.press("ControlOrMeta+KeyK");
    await expect(searchInput).toBeFocused();
  });
});
