import { test, expect } from "@playwright/test";

test.describe("Knowledge-Guided Analysis Workspace Integration E2E", () => {
  const completedRepoId = "8962366c-b33a-49d9-a4e0-919384c6665b"; // Portfolio (indexed)

  test("renders Analysis tab, toggles scopes, executes analysis and displays separate evidence", async ({
    page,
  }) => {
    // Mock /knowledge endpoint to ensure consistent knowledge scopes exist in test
    await page.route("**/knowledge", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "0e3e4d53-15dd-46a1-b284-49be5d99a6db",
              name: "Design Patterns Reference Guide",
              description: "GoF patterns and principles",
              status: "completed",
              error_message: null,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              documents: [
                {
                  id: "156b4de2-ff3d-40b9-b516-579e784a0afe",
                  knowledge_id: "0e3e4d53-15dd-46a1-b284-49be5d99a6db",
                  filename: "design_patterns_reference.pdf",
                  source_type: "pdf",
                  file_size_bytes: 4096,
                  status: "completed",
                  error_message: null,
                  chunks_count: 3,
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                },
              ],
            },
          ]),
        });
      } else {
        await route.continue();
      }
    });

    // Mock /analysis/knowledge endpoint
    await page.route("**/analysis/knowledge", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 300));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer:
            "Based on the engineering knowledge provided, the **Strategy Pattern** is recommended for refactoring this component. It allows interchangeable algorithms while adhering to the Open/Closed Principle.",
          sources: [
            {
              source_id: "src_1",
              type: "repository",
              label: "app/page.tsx:1-45",
              path: "app/page.tsx",
              start_line: 1,
              end_line: 45,
              page_number: null,
            },
            {
              source_id: "src_4",
              type: "knowledge",
              label: "design_patterns_reference.pdf, page 1",
              path: "design_patterns_reference.pdf",
              start_line: null,
              end_line: null,
              page_number: 1,
            },
          ],
        }),
      });
    });

    // 1. Navigate to repository workspace
    await page.goto(`/repositories/${completedRepoId}`);

    // 2. Click Analysis tab
    const analysisTab = page.getByTestId("tab-analysis");
    await expect(analysisTab).toBeVisible();
    await analysisTab.click();

    // 3. Verify Knowledge Analysis panel is displayed
    const panel = page.getByTestId("knowledge-analysis-panel");
    await expect(panel).toBeVisible();

    // 4. Verify scope selection controls
    const scopeSelect = page.getByTestId("knowledge-scope-select");
    await expect(scopeSelect).toBeVisible();
    await expect(scopeSelect).toContainText("Design Patterns Reference Guide");

    // Code scope toggle: Repository vs Specific File
    const repoScopeBtn = page.getByTestId("code-scope-repo");
    const fileScopeBtn = page.getByTestId("code-scope-file");
    await expect(repoScopeBtn).toBeVisible();
    await expect(fileScopeBtn).toBeVisible();

    // Toggle to Specific File
    await fileScopeBtn.click();
    const filePicker = page.getByTestId("file-scope-selector");
    await expect(filePicker).toBeVisible();

    // 5. Test validation: Analyze button disabled with empty question
    const analyzeBtn = page.getByTestId("run-analysis-button");
    const questionInput = page.getByTestId("analysis-question-input");
    await expect(analyzeBtn).toBeDisabled();

    // Enter question
    await questionInput.fill("What pattern would you suggest for this component?");
    await expect(analyzeBtn).toBeEnabled();

    // 6. Execute analysis
    await analyzeBtn.click();

    // 7. Verify Answer card is displayed
    const answerCard = page.getByTestId("analysis-answer");
    await expect(answerCard).toBeVisible();
    await expect(answerCard).toContainText("Strategy Pattern");

    // 8. Verify Repository Evidence and Knowledge Evidence are visually distinguished
    const repoEvidence = page.getByTestId("repository-evidence-section");
    await expect(repoEvidence).toBeVisible();
    await expect(repoEvidence).toContainText("Repository Evidence");
    await expect(repoEvidence.getByTestId("repo-source-0")).toContainText("app/page.tsx");
    await expect(repoEvidence.getByTestId("open-repo-source-0")).toBeVisible();

    const knowledgeEvidence = page.getByTestId("knowledge-evidence-section");
    await expect(knowledgeEvidence).toBeVisible();
    await expect(knowledgeEvidence).toContainText("Engineering Knowledge Evidence");
    await expect(knowledgeEvidence.getByTestId("knowledge-source-0")).toContainText(
      "design_patterns_reference.pdf"
    );
    await expect(knowledgeEvidence.getByText("Page 1")).toBeVisible();

    // 9. Reset button clears results
    const clearBtn = page.getByTestId("reset-analysis-button");
    await expect(clearBtn).toBeVisible();
    await clearBtn.click();
    await expect(page.getByTestId("analysis-results")).toBeHidden();
  });

  test("shows warning when no engineering knowledge scopes exist", async ({ page }) => {
    // Mock empty /knowledge list
    await page.route("**/knowledge", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.goto(`/repositories/${completedRepoId}?tab=analysis`);

    const warning = page.getByTestId("no-knowledge-warning");
    await expect(warning).toBeVisible();
    await expect(warning).toContainText("No Engineering Knowledge Scopes");
    await expect(page.getByRole("button", { name: "Manage Knowledge" })).toBeVisible();
  });
});
