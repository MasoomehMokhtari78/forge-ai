import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";

test.use({
  video: {
    mode: "on",
    size: { width: 1440, height: 900 },
  },
  viewport: { width: 1440, height: 900 },
});

test("records full ForgeAI end-to-end demo tour with backend architecture", async ({ page, context }) => {
  test.setTimeout(120000);

  const screenshotsDir = path.resolve(__dirname, "../../docs/screenshots");
  if (!fs.existsSync(screenshotsDir)) {
    fs.mkdirSync(screenshotsDir, { recursive: true });
  }

  // 1. Dashboard: Repositories List
  await page.goto("/repositories");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);

  await expect(page.getByRole("heading", { name: "Repositories" })).toBeVisible();
  await page.screenshot({
    path: path.join(screenshotsDir, "01-dashboard.png"),
    fullPage: false,
  });

  // 2. Open Repository Workspace (forge-ai)
  const repoCard = page.locator('a[href*="fcbbe1db-7f95-45b1-8adc-339347486b83"]').first();
  await expect(repoCard).toBeVisible();
  await repoCard.hover();
  await page.waitForTimeout(1000);
  await repoCard.click();

  // Wait for workspace layout
  await page.waitForURL(/\/repositories\/fcbbe1db-7f95-45b1-8adc-339347486b83/);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);

  // Expand backend -> app -> services -> embedding.py
  const backendFolder = page.locator('button:has-text("backend")').first();
  if (await backendFolder.isVisible()) {
    await backendFolder.click();
    await page.waitForTimeout(600);
  }
  const appFolder = page.locator('button:has-text("app")').first();
  if (await appFolder.isVisible()) {
    await appFolder.click();
    await page.waitForTimeout(600);
  }
  const servicesFolder = page.locator('button:has-text("services")').first();
  if (await servicesFolder.isVisible()) {
    await servicesFolder.click();
    await page.waitForTimeout(600);
  }
  const embeddingFile = page.locator('button:has-text("embedding.py")').first();
  if (await embeddingFile.isVisible()) {
    await embeddingFile.click();
    await page.waitForTimeout(1500);
  }

  await page.screenshot({
    path: path.join(screenshotsDir, "02-workspace.png"),
    fullPage: false,
  });

  // 3. Showcase Semantic Search
  const searchTab = page.getByTestId("tab-search");
  await searchTab.click();
  await page.waitForTimeout(1000);

  const searchInput = page.locator('input[placeholder*="search" i], input[type="search"], input[type="text"]').last();
  await searchInput.fill("SentenceTransformer embedding provider vector dimension");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(2500);

  await page.screenshot({
    path: path.join(screenshotsDir, "03-semantic-search.png"),
    fullPage: false,
  });

  // Click top search result to highlight code viewer
  const topResult = page.locator('[data-testid^="search-result-"]').first();
  if (await topResult.isVisible()) {
    await topResult.click();
    await page.waitForTimeout(1500);
  }

  // 4. Showcase Knowledge-Guided Analysis (Backend Architecture + GoF Patterns)
  const analysisTab = page.getByTestId("tab-analysis");
  await analysisTab.click();
  await page.waitForTimeout(1500);

  const scopeSelect = page.getByTestId("knowledge-scope-select");
  await expect(scopeSelect).toBeVisible();

  // Select "Design Patterns" scope
  try {
    await scopeSelect.selectOption("912f165f-df03-46da-bea3-fc8421772a89");
  } catch {
    // Keep current selection
  }
  await page.waitForTimeout(800);

  // Toggle Specific File scope for targeted architectural analysis
  const fileScopeBtn = page.getByTestId("code-scope-file");
  if (await fileScopeBtn.isVisible()) {
    await fileScopeBtn.click();
    await page.waitForTimeout(600);
  }

  const questionInput = page.getByTestId("analysis-question-input");
  await questionInput.fill(
    "Analyze this file and evaluate how the Factory Method and Strategy patterns are applied to manage different embedding providers."
  );
  await page.waitForTimeout(1000);

  const analyzeBtn = page.getByTestId("run-analysis-button");
  await expect(analyzeBtn).toBeEnabled();
  await analyzeBtn.click();

  // Wait for synthesis results with citations (~10-15s with local Ollama)
  const answerCard = page.getByTestId("analysis-answer");
  await expect(answerCard).toBeVisible({ timeout: 60000 });
  await page.waitForTimeout(2000);

  // Scroll to show dual evidence: Repository Evidence and Knowledge Evidence with page citations
  const resultsContainer = page.getByTestId("knowledge-analysis-panel");
  await resultsContainer.evaluate((el) => {
    el.scrollTop = 220;
  });
  await page.waitForTimeout(1500);

  await page.screenshot({
    path: path.join(screenshotsDir, "04-knowledge-analysis.png"),
    fullPage: false,
  });

  // 5. Showcase Engineering Knowledge Management
  await page.goto("/knowledge");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2500);

  await expect(page.getByRole("heading", { name: "Engineering Knowledge" })).toBeVisible();

  // Find Design Patterns scope card showing Head First Design Patterns (49.9 MB, 1,461 chunks)
  const dpCard = page.locator('[data-testid^="knowledge-scope-card-"]:has-text("Design Patterns")').first();
  await expect(dpCard).toBeVisible();

  await page.screenshot({
    path: path.join(screenshotsDir, "05-knowledge-management.png"),
    fullPage: false,
  });

  // Hover and click refresh to demonstrate interactive action & toast
  const refreshBtn = page.getByTestId("refresh-knowledge-button");
  await refreshBtn.click();
  await page.waitForTimeout(2000);

  // 6. Return cleanly to Repositories Dashboard
  await page.goto("/repositories");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);

  // Obtain video before context close
  const video = page.video();
  await page.close();
  await context.close();

  if (video) {
    const videoDest = path.resolve(__dirname, "../../docs/demo.webm");
    await video.saveAs(videoDest);
    console.log("Demo video saved successfully to:", videoDest);
  }
});
