import { test, expect } from "@playwright/test";
import path from "path";

test.describe("Engineering Knowledge Management E2E", () => {
  const uniqueSuffix = Date.now().toString().slice(-6);
  const scopeName = `Clean Architecture Reference ${uniqueSuffix}`;
  const scopeDesc = "SOLID principles and design guidelines for testing";
  const fixturePdfPath = path.resolve(__dirname, "fixtures/test_reference.pdf");

  test("manages full knowledge lifecycle: create scope, upload PDF, view doc, delete doc, delete scope", async ({
    page,
  }) => {
    test.setTimeout(60000);

    // 1. Open knowledge management page
    await page.goto("/knowledge");

    // Verify page header and actions
    await expect(page.getByRole("heading", { name: "Engineering Knowledge" })).toBeVisible();
    await expect(page.getByTestId("open-create-knowledge-button")).toBeVisible();

    // 2. Open Create Knowledge dialog
    await page.getByTestId("open-create-knowledge-button").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByTestId("create-knowledge-submit")).toBeDisabled();

    // Fill form
    await page.getByTestId("knowledge-name-input").fill(scopeName);
    await page.getByTestId("knowledge-desc-input").fill(scopeDesc);
    await expect(page.getByTestId("create-knowledge-submit")).toBeEnabled();

    // Submit dialog
    await page.getByTestId("create-knowledge-submit").click();
    await expect(page.getByRole("dialog")).toBeHidden();

    // 3. Verify scope appears in list
    const scopeCard = page.locator(`[data-testid^="knowledge-scope-card-"]:has-text("${scopeName}")`);
    await expect(scopeCard).toBeVisible();
    await expect(scopeCard.getByTestId("scope-name")).toHaveText(scopeName);
    await expect(scopeCard.getByText(scopeDesc)).toBeVisible();

    // 4. Upload PDF fixture into the scope
    const fileChooserPromise = page.waitForEvent("filechooser");
    await scopeCard.getByTestId(/upload-pdf-button-/).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(fixturePdfPath);

    // 5. Verify the uploaded document row appears
    const docRow = scopeCard.getByTestId(/document-row-/);
    await expect(docRow).toBeVisible({ timeout: 35000 });
    await expect(docRow.getByTestId("doc-filename")).toContainText("test_reference.pdf");

    // Verify document status badge is present (e.g. Completed or Processing)
    await expect(docRow.getByTestId("knowledge-status-badge")).toBeVisible();

    // 6. Delete document
    page.once("dialog", async (dialog) => {
      await dialog.accept();
    });
    await docRow.getByTestId(/delete-doc-button-/).click();

    // Verify document row disappears
    await expect(scopeCard.getByText("test_reference.pdf")).toBeHidden({ timeout: 10000 });
    await expect(
      scopeCard.getByText("No PDF documents uploaded yet")
    ).toBeVisible();

    // 7. Delete knowledge scope
    page.once("dialog", async (dialog) => {
      await dialog.accept();
    });
    await scopeCard.getByTestId(/delete-scope-button-/).click();

    // Verify scope card is deleted
    await expect(page.locator(`text="${scopeName}"`)).toBeHidden({ timeout: 10000 });
  });

  test("validates required scope name in create dialog", async ({ page }) => {
    await page.goto("/knowledge");
    await page.getByTestId("open-create-knowledge-button").click();

    const submitBtn = page.getByTestId("create-knowledge-submit");
    await expect(submitBtn).toBeDisabled();

    // Fill only whitespace
    await page.getByTestId("knowledge-name-input").fill("   ");
    await expect(submitBtn).toBeDisabled();

    // Fill valid name
    await page.getByTestId("knowledge-name-input").fill("Valid Scope Name");
    await expect(submitBtn).toBeEnabled();

    // Cancel closes dialog cleanly
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("dialog")).toBeHidden();
  });
});
