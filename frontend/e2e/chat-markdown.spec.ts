import { test, expect } from "@playwright/test";

test.describe("Chat Panel - Markdown Display & Formatting", () => {
  const completedRepoId = "8962366c-b33a-49d9-a4e0-919384c6665b";

  test("renders rich markdown formatting including code blocks, headings, tables, and lists", async ({
    page,
  }) => {
    // Intercept chat API to return rich markdown
    const sampleMarkdown = `
# Project Overview

Here is an explanation of the architecture. You can configure it in \`config.json\`.

### Core Features
* Fast indexing with **pgvector**
* Hybrid lexical & *semantic* retrieval
* Deterministic citations

### Implementation Example
\`\`\`typescript
interface Config {
  apiKey: string;
  maxTokens: number;
}

export function initConfig(): Config {
  return { apiKey: "forge-123", maxTokens: 4000 };
}
\`\`\`

### Data Schema
| Field | Type | Description |
| :--- | :--- | :--- |
| id | string | Unique record ID |
| score | number | Relevance ranking score |

For further details, visit [ForgeAI Documentation](https://github.com/forgeai).
`;

    await page.route(`**/repositories/${completedRepoId}/chat`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: sampleMarkdown.trim(),
          sources: [
            {
              path: "app/core/config.py",
              start_line: 10,
              end_line: 25,
            },
          ],
        }),
      });
    });

    await page.goto(`/repositories/${completedRepoId}`);

    const chatInput = page.getByTestId("chat-input");
    const sendButton = page.getByTestId("chat-send-button");

    await chatInput.fill("Tell me about the project configuration");
    await sendButton.click();

    const assistantMessage = page.getByTestId("chat-assistant-message");
    await expect(assistantMessage).toBeVisible();

    // 1. Verify Headings rendered as HTML headings
    const h1 = assistantMessage.locator("h1");
    await expect(h1).toHaveText("Project Overview");

    const h3 = assistantMessage.locator("h3").first();
    await expect(h3).toHaveText("Core Features");

    // 2. Verify Bold and Inline Code
    const strong = assistantMessage.locator("strong").first();
    await expect(strong).toHaveText("pgvector");

    const inlineCode = assistantMessage.locator("code").filter({ hasText: "config.json" });
    await expect(inlineCode).toBeVisible();

    // 3. Verify Lists
    const listItems = assistantMessage.locator("ul li");
    await expect(listItems).toHaveCount(3);

    // 4. Verify Code Block with Language Badge, Syntax Highlighted Code, and Copy Button
    const codeBlockBadge = assistantMessage.getByText("typescript", { exact: true });
    await expect(codeBlockBadge).toBeVisible();

    const copyBtn = assistantMessage.getByTitle("Copy code");
    await expect(copyBtn).toBeVisible();

    // 5. Verify Table Structure
    const table = assistantMessage.locator("table");
    await expect(table).toBeVisible();
    await expect(table.locator("th").first()).toHaveText("Field");
    await expect(table.locator("td").first()).toHaveText("id");

    // 6. Verify Links
    const docLink = assistantMessage.locator('a[href="https://github.com/forgeai"]');
    await expect(docLink).toBeVisible();
    await expect(docLink).toHaveAttribute("target", "_blank");

    // 7. Verify Sources section is still displayed below markdown
    const sources = page.getByTestId("chat-sources");
    await expect(sources).toBeVisible();
  });
});
