import { test, expect } from "@playwright/test";

test.describe("Repository Workspace - File Viewer Vertical Slice", () => {
  const repoId = "8962366c-b33a-49d9-a4e0-919384c6665b"; // MasoomehMokhtari78/Portfolio

  test("renders file explorer with folders and root files", async ({ page }) => {
    await page.goto(`/repositories/${repoId}`);

    // File tree container should be visible
    const fileTree = page.getByTestId("file-tree");
    await expect(fileTree).toBeVisible();

    // Verify folder nodes exist
    await expect(page.getByTestId("folder-app")).toBeVisible();
    await expect(page.getByTestId("folder-components")).toBeVisible();

    // Default overview should be shown when no file is selected
    await expect(page.getByTestId("workspace-overview")).toBeVisible();
    await expect(page.getByTestId("code-viewer")).not.toBeVisible();
  });

  test("expands and collapses folders when clicked", async ({ page }) => {
    await page.goto(`/repositories/${repoId}`);

    const appFolder = page.getByTestId("folder-app");
    await expect(appFolder).toBeVisible();

    // Initially "app" folder is collapsed
    await expect(appFolder).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("file-layout.tsx")).not.toBeVisible();

    // Click to expand "app" folder
    await appFolder.click();
    await expect(appFolder).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("file-layout.tsx")).toBeVisible();

    // Click again to collapse "app" folder
    await appFolder.click();
    await expect(appFolder).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("file-layout.tsx")).not.toBeVisible();
  });

  test("filters file tree using search input", async ({ page }) => {
    await page.goto(`/repositories/${repoId}`);

    const searchInput = page.getByTestId("file-search-input");
    await expect(searchInput).toBeVisible();

    // Search for "button"
    await searchInput.fill("button");

    // "button.tsx" should be visible
    await expect(page.getByTestId("file-button.tsx")).toBeVisible();

    // Other files like "layout.tsx" should not be visible
    await expect(page.getByTestId("file-layout.tsx")).not.toBeVisible();

    // Clear search using the clear button
    const clearButton = page.getByTitle("Clear search");
    await clearButton.click();
    await expect(searchInput).toHaveValue("");

    // Folder "components" should be visible again
    await expect(page.getByTestId("folder-components")).toBeVisible();
  });

  test("selects a file, updates URL query param, and renders source code with line numbers", async ({
    page,
  }) => {
    await page.goto(`/repositories/${repoId}`);

    // Expand the "app" folder
    const appFolder = page.getByTestId("folder-app");
    await appFolder.click();

    // Click "layout.tsx"
    const layoutFile = page.getByTestId("file-layout.tsx");
    await layoutFile.click();

    // URL should update to include ?file=app/layout.tsx
    await expect(page).toHaveURL(/file=app%2Flayout\.tsx|file=app\/layout\.tsx/);

    // CodeViewer should now be visible and workspace overview hidden
    const codeViewer = page.getByTestId("code-viewer");
    await expect(codeViewer).toBeVisible();
    await expect(page.getByTestId("workspace-overview")).not.toBeVisible();

    // Breadcrumb path inside CodeViewer
    await expect(codeViewer.getByText("layout.tsx")).toBeVisible();

    // Badges: Language and Line count
    await expect(codeViewer.getByText("TSX", { exact: true })).toBeVisible();
    await expect(codeViewer.getByText(/lines/)).toBeVisible();

    // Line numbers gutter
    const gutter = page.getByTestId("line-numbers-gutter");
    await expect(gutter).toBeVisible();
    await expect(gutter.getByText("1", { exact: true })).toBeVisible();

    // Code container should contain real code content
    const codeContainer = page.getByTestId("code-container");
    await expect(codeContainer).toContainText("export default");

    // Copy button should be present
    const copyButton = page.getByTestId("copy-code-button");
    await expect(copyButton).toBeVisible();
  });

  test("deep-linking via ?file=... loads the file directly and auto-expands parent folder", async ({
    page,
  }) => {
    await page.goto(`/repositories/${repoId}?file=app/layout.tsx`);

    // Code viewer should render layout.tsx directly without manual clicks
    const codeViewer = page.getByTestId("code-viewer");
    await expect(codeViewer).toBeVisible();
    await expect(codeViewer.getByText("layout.tsx")).toBeVisible();
    await expect(page.getByTestId("code-container")).toContainText("export default");

    // In the file tree, "app" folder should be auto-expanded and file selected
    const appFolder = page.getByTestId("folder-app");
    await expect(appFolder).toHaveAttribute("aria-expanded", "true");
    const layoutFile = page.getByTestId("file-layout.tsx");
    await expect(layoutFile).toHaveAttribute("data-selected", "true");
  });

  test("closing the selected file restores repository overview", async ({ page }) => {
    await page.goto(`/repositories/${repoId}?file=app/layout.tsx`);

    await expect(page.getByTestId("code-viewer")).toBeVisible();

    // Click close file button in the top breadcrumbs
    const closeButton = page.getByTestId("close-file-button");
    await closeButton.click();

    // URL should no longer contain ?file=
    await expect(page).toHaveURL(`/repositories/${repoId}`);

    // Overview should be restored
    await expect(page.getByTestId("workspace-overview")).toBeVisible();
    await expect(page.getByTestId("code-viewer")).not.toBeVisible();
  });

  test("displays graceful error state for non-existent file path", async ({ page }) => {
    await page.goto(`/repositories/${repoId}?file=nonexistent/path/missing.ts`);

    // Error container should be rendered
    const errorContainer = page.getByTestId("code-viewer-error");
    await expect(errorContainer).toBeVisible();
    await expect(errorContainer.getByText("Unable to load file")).toBeVisible();
    await expect(errorContainer.getByText(/not found/i)).toBeVisible();

    // Retry button should be available
    await expect(page.getByTestId("code-viewer-retry-button")).toBeVisible();
  });
});
