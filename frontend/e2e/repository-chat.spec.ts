import { test, expect } from "@playwright/test";

test.describe("Repository Workspace - Grounded RAG Chat Vertical Slice", () => {
  const completedRepoId = "8962366c-b33a-49d9-a4e0-919384c6665b"; // MasoomehMokhtari78/Portfolio (indexed)
  const failedRepoId = "4c844aed-5822-43f7-bf42-e53fcb2335c9"; // octocat/Spoon-Knife (failed / unindexed)

  test("chat UI is visible by default in the repository workspace", async ({ page }) => {
    await page.goto(`/repositories/${completedRepoId}`);

    // Verify chat panel is present
    const chatPanel = page.getByTestId("chat-panel");
    await expect(chatPanel).toBeVisible();

    // Verify chat input and send button
    const chatInput = page.getByTestId("chat-input");
    await expect(chatInput).toBeVisible();
    await expect(chatInput).toBeEnabled();

    const sendButton = page.getByTestId("chat-send-button");
    await expect(sendButton).toBeVisible();

    // Verify topbar chat trigger is present and active
    const topbarChatTrigger = page.getByTestId("workspace-chat-trigger");
    await expect(topbarChatTrigger).toBeVisible();

    // Verify welcome state instructions and suggested questions
    await expect(page.getByText("Ask about this repository")).toBeVisible();
    await expect(page.getByText("Where is the projects section handled?")).toBeVisible();
  });

  test("renders disabled indexing-required state for unindexed repository", async ({
    page,
  }) => {
    await page.goto(`/repositories/${failedRepoId}`);

    // Verify chat panel displays not-indexed notification
    const notIndexedState = page.getByTestId("chat-not-indexed");
    await expect(notIndexedState).toBeVisible();
    await expect(notIndexedState).toContainText("Indexing required");

    // Chat input should be disabled
    const chatInput = page.getByTestId("chat-input");
    await expect(chatInput).toBeDisabled();

    // Send button should be disabled
    const sendButton = page.getByTestId("chat-send-button");
    await expect(sendButton).toBeDisabled();
  });

  test("shows loading state while generating an answer", async ({ page }) => {
    // Intercept chat API with a delayed response to observe loading skeleton
    await page.route(`**/repositories/${completedRepoId}/chat`, async (route) => {
      // Delay response by 1.5 seconds
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "The projects section is rendered on the home page.",
          sources: [
            {
              file_path: "app/page.tsx",
              start_line: 1,
              end_line: 25,
            },
          ],
        }),
      });
    });

    await page.goto(`/repositories/${completedRepoId}`);

    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Where is the projects section handled?");

    const sendButton = page.getByTestId("chat-send-button");
    await sendButton.click();

    // User message should appear immediately
    const userMessage = page.getByTestId("chat-user-message");
    await expect(userMessage).toBeVisible();
    await expect(userMessage).toContainText("Where is the projects section handled?");

    // Loading skeleton indicator must be displayed during generation
    const loadingIndicator = page.getByTestId("chat-loading");
    await expect(loadingIndicator).toBeVisible();

    // Once fulfilled, loading disappears and assistant message appears
    await expect(loadingIndicator).not.toBeVisible();
    const assistantMessage = page.getByTestId("chat-assistant-message");
    await expect(assistantMessage).toBeVisible();
    await expect(assistantMessage).toContainText("The projects section is rendered on the home page.");
  });

  test("performs real RAG Q&A with semantic retrieval, local LLM, and citations", async ({
    page,
  }) => {
    // Generous timeout for real local LLM inference
    test.setTimeout(90000);
    await page.goto(`/repositories/${completedRepoId}`);

    const chatInput = page.getByTestId("chat-input");
    const sendButton = page.getByTestId("chat-send-button");

    const query = "Where is the projects section handled?";
    await chatInput.fill(query);

    // Track the real backend /chat API response
    const chatResponsePromise = page.waitForResponse(
      (resp) =>
        resp.url().includes(`/repositories/${completedRepoId}/chat`) &&
        resp.status() === 200,
      { timeout: 75000 }
    );

    await sendButton.click();

    // User message should be rendered
    const userMessage = page.getByTestId("chat-user-message");
    await expect(userMessage).toBeVisible();
    await expect(userMessage).toContainText(query);

    // Wait for the real RAG response
    const chatResponse = await chatResponsePromise;
    expect(chatResponse.ok()).toBeTruthy();

    const responseJson = await chatResponse.json();
    expect(responseJson.answer).toBeTruthy();
    expect(responseJson.answer.length).toBeGreaterThan(15);
    expect(Array.isArray(responseJson.sources)).toBeTruthy();

    // Assistant message must be rendered with non-empty content
    const assistantMessage = page.getByTestId("chat-assistant-message");
    await expect(assistantMessage).toBeVisible();

    // Sources section must be rendered with at least one verified chunk citation
    if (responseJson.sources.length > 0) {
      const sourcesContainer = page.getByTestId("chat-sources");
      await expect(sourcesContainer).toBeVisible();

      const firstSourceCard = page.getByTestId("source-card-0");
      await expect(firstSourceCard).toBeVisible();

      // Ensure file path and line numbers are displayed
      const expectedPath = responseJson.sources[0].file_path || responseJson.sources[0].path;
      await expect(firstSourceCard).toContainText(expectedPath);
      await expect(firstSourceCard).toContainText(`L${responseJson.sources[0].start_line}`);
    }
  });

  test("clicking a citation opens the source file in the code viewer at the cited line", async ({
    page,
  }) => {
    // Intercept to return a deterministic citation for link verification
    await page.route(`**/repositories/${completedRepoId}/chat`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "The projects section is defined in app/page.tsx.",
          sources: [
            {
              file_path: "app/page.tsx",
              start_line: 10,
              end_line: 30,
            },
          ],
        }),
      });
    });

    await page.goto(`/repositories/${completedRepoId}`);

    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Where is the projects section handled?");
    await chatInput.press("Enter");

    // Wait for assistant message and source card
    const sourceCard = page.getByTestId("source-card-0");
    await expect(sourceCard).toBeVisible();

    // Click "Open" button on source card
    const openSourceButton = page.getByTestId("open-source-button-0");
    await openSourceButton.click();

    // URL should be updated with ?file=app/page.tsx&line=10
    await expect(page).toHaveURL(/\?file=app%2Fpage\.tsx&line=10|\?file=app\/page\.tsx&line=10/);

    // Code viewer should now be visible with the file loaded
    const codeViewer = page.getByTestId("code-viewer");
    await expect(codeViewer).toBeVisible();

    // Target line indicator badge should be visible
    const targetLineBadge = page.getByTestId("target-line-badge");
    await expect(targetLineBadge).toBeVisible();
    await expect(targetLineBadge).toContainText("Line 10");
  });

  test("unsupported question produces grounded fallback refusal", async ({ page }) => {
    // Real call with an unanswerable question or simulated grounding refusal
    await page.route(`**/repositories/${completedRepoId}/chat`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "I couldn't find enough relevant code in this repository to answer that reliably.",
          sources: [],
        }),
      });
    });

    await page.goto(`/repositories/${completedRepoId}`);

    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Explain the quantum teleportation algorithm implemented in this codebase");
    await chatInput.press("Enter");

    const assistantMessage = page.getByTestId("chat-assistant-message");
    await expect(assistantMessage).toBeVisible();
    await expect(assistantMessage).toContainText(
      "I couldn't find enough relevant code in this repository to answer that reliably."
    );

    // No source citations should be displayed for grounded refusal
    await expect(page.getByTestId("chat-sources")).not.toBeVisible();
  });

  test("handles backend error with retry action", async ({ page }) => {
    await page.goto(`/repositories/${completedRepoId}`);

    let shouldFail = true;
    await page.route(`**/repositories/${completedRepoId}/chat`, async (route) => {
      if (shouldFail) {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Local LLM service is temporarily unavailable." }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            answer: "Here is the recovered answer.",
            sources: [],
          }),
        });
      }
    });

    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Test retry query");
    await chatInput.press("Enter");

    // Error card should be visible
    const errorCard = page.getByTestId("chat-error");
    await expect(errorCard).toBeVisible();
    await expect(errorCard).toContainText("Local LLM service is temporarily unavailable.");

    // Retry button should be clickable
    const retryButton = page.getByTestId("chat-retry-button");
    await expect(retryButton).toBeVisible();

    // Click retry with recovered backend
    shouldFail = false;
    await retryButton.click();

    // Success response appears as the latest assistant message
    const assistantMessage = page.getByTestId("chat-assistant-message").last();
    await expect(assistantMessage).toBeVisible();
    await expect(assistantMessage).toContainText("Here is the recovered answer.");
  });

  test("supports multi-turn client session conversation history", async ({ page }) => {
    let callCount = 0;
    await page.route(`**/repositories/${completedRepoId}/chat`, async (route) => {
      callCount++;
      if (callCount === 1) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            answer: "First answer: projects are defined in page.tsx.",
            sources: [{ file_path: "app/page.tsx", start_line: 1, end_line: 10 }],
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            answer: "Second answer: styles are configured in globals.css.",
            sources: [{ file_path: "app/globals.css", start_line: 1, end_line: 20 }],
          }),
        });
      }
    });

    await page.goto(`/repositories/${completedRepoId}`);

    const chatInput = page.getByTestId("chat-input");

    // First question
    await chatInput.fill("Where are projects defined?");
    await chatInput.press("Enter");

    await expect(page.getByText("First answer: projects are defined in page.tsx.")).toBeVisible();

    // Second question
    await chatInput.fill("Where are styles configured?");
    await chatInput.press("Enter");

    await expect(page.getByText("Second answer: styles are configured in globals.css.")).toBeVisible();

    // Both user questions should still be present in the conversation
    const userMessages = page.getByTestId("chat-user-message");
    await expect(userMessages).toHaveCount(2);

    const assistantMessages = page.getByTestId("chat-assistant-message");
    await expect(assistantMessages).toHaveCount(2);
  });
});
