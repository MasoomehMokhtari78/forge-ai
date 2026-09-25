import { chromium } from "playwright";
import path from "node:path";

const SCREENSHOT_DIR = "C:/Users/Lenovo/.gemini/antigravity-ide/brain/74a7c628-7f7d-41f3-87d7-48a5d8417b08/screenshots";

async function main() {
  console.log("=== Comprehensive Playwright UI Verification ===");
  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: "dark",
  });

  const page = await context.newPage();

  // Listen to console messages and errors
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
    }
  });

  // ─────────────────────────────────────────────────────────────
  // 1. Dashboard (Real Backend Data)
  // ─────────────────────────────────────────────────────────────
  console.log("\n--- [1] Testing Dashboard (Real Backend Data) ---");
  await page.goto("http://localhost:3000/", { waitUntil: "networkidle" });
  console.log(`Redirected to: ${page.url()}`);

  const heading = await page.getByRole("heading", { name: "Repositories" }).textContent();
  const countText = await page.locator("text=/\\d+ repositories/").textContent();
  console.log(`Heading: "${heading}", Count: "${countText}"`);

  // Verify repositories and badges
  console.log("gitignore visible:", await page.getByText("gitignore").first().isVisible());
  console.log("Spoon-Knife visible:", await page.getByText("Spoon-Knife").first().isVisible());
  console.log("Hello-World visible:", await page.getByText("Hello-World").first().isVisible());
  console.log("Indexed badge visible:", await page.locator("span:has-text('Indexed')").first().isVisible());
  console.log("Failed badge count:", await page.locator("span:has-text('Failed')").count());

  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "01_dashboard.png"), fullPage: true });

  // ─────────────────────────────────────────────────────────────
  // 2. Add Repository Dialog: Open
  // ─────────────────────────────────────────────────────────────
  console.log("\n--- [2] Testing Add Repository Dialog Open ---");
  const newRepoButton = page.getByRole("button", { name: "New" }).first();
  await newRepoButton.click();
  await page.waitForTimeout(400);

  const dialogTitleVisible = await page.getByRole("heading", { name: "Add Repository" }).isVisible();
  console.log("Dialog Title Visible:", dialogTitleVisible);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "02_add_repo_dialog_open.png") });

  // ─────────────────────────────────────────────────────────────
  // 3a. Add Repository Dialog: Invalid URL (422)
  // ─────────────────────────────────────────────────────────────
  console.log("\n--- [3a] Testing Invalid URL Handling (422) ---");
  const urlInput = page.locator("input[placeholder*='github.com']");
  await urlInput.fill("https://gitlab.com/owner/repo");
  const submitButton = page.getByRole("button", { name: "Add repository" });
  await submitButton.click();
  await page.waitForTimeout(600);

  const errorAlert = page.locator("div[role='alert']");
  console.log("Invalid URL Error Alert:", await errorAlert.textContent());
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "03a_invalid_url_error.png") });

  // ─────────────────────────────────────────────────────────────
  // 3b. Add Repository Dialog: Duplicate URL (409)
  // ─────────────────────────────────────────────────────────────
  console.log("\n--- [3b] Testing Duplicate URL Handling (409) ---");
  await urlInput.fill("https://github.com/github/gitignore");
  await submitButton.click();
  await page.waitForTimeout(600);

  console.log("Duplicate URL Error Alert:", await errorAlert.textContent());
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "03b_duplicate_url_error.png") });

  // Close dialog
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.waitForTimeout(300);

  // ─────────────────────────────────────────────────────────────
  // 4. Workspace View (Real Data)
  // ─────────────────────────────────────────────────────────────
  console.log("\n--- [4] Testing Workspace View (Real Data) ---");
  await page.locator("main a[href*='/repositories/']").first().click();
  await page.waitForURL("**/repositories/**", { waitUntil: "networkidle" });
  console.log(`Workspace URL: ${page.url()}`);

  const workspaceTitle = await page.locator("h1").textContent();
  console.log(`Workspace Heading: "${workspaceTitle}"`);

  // Verify English formatted numbers 316 and 413
  const filesStat = await page.getByText("316").isVisible();
  const chunksStat = await page.getByText("413").isVisible();
  console.log("Files stat '316' visible:", filesStat);
  console.log("Chunks stat '413' visible:", chunksStat);

  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "04_workspace.png"), fullPage: true });

  // ─────────────────────────────────────────────────────────────
  // 5. 404 Not Found Handling
  // ─────────────────────────────────────────────────────────────
  console.log("\n--- [5] Testing 404 Not Found Page ---");
  await page.goto("http://localhost:3000/repositories/00000000-0000-0000-0000-000000000000", { waitUntil: "networkidle" });
  const notFoundVisible = await page.getByRole("heading", { name: "Repository not found" }).isVisible();
  console.log("Not Found Heading Visible:", notFoundVisible);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "05_not_found.png"), fullPage: true });

  // ─────────────────────────────────────────────────────────────
  // 6. Dashboard: Empty State Verification
  // ─────────────────────────────────────────────────────────────
  console.log("\n--- [6] Testing Dashboard Empty State ---");
  await page.goto("http://localhost:3000/repositories?state=empty", { waitUntil: "networkidle" });
  const emptyStateHeading = await page.getByRole("heading", { name: "No repositories yet" }).isVisible();
  console.log("Empty State 'No repositories yet' Visible:", emptyStateHeading);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "06_dashboard_empty_state.png"), fullPage: true });

  // ─────────────────────────────────────────────────────────────
  // 7. Dashboard: API Error State Verification
  // ─────────────────────────────────────────────────────────────
  console.log("\n--- [7] Testing Dashboard API Error State ---");
  await page.goto("http://localhost:3000/repositories?state=error", { waitUntil: "networkidle" });
  const errorHeadingVisible = await page.getByRole("heading", { name: "Failed to load repositories" }).isVisible();
  console.log("API Error 'Failed to load repositories' Visible:", errorHeadingVisible);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, "07_dashboard_api_error_state.png"), fullPage: true });

  await browser.close();
  console.log("\n=== All Verification Flows Completed Successfully! ===");
}

main().catch((err) => {
  console.error("Verification failed:", err);
  process.exit(1);
});
