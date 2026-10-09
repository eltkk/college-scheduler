import { test, expect } from "@playwright/test";

test("import archive distinguishes loading, failure, retry and an empty result", async ({ page }) => {
  test.skip(!process.env.E2E_LOGIN || !process.env.E2E_PASSWORD,
    "Use the disposable CI environment, never a production workspace");
  await page.goto("/");
  await page.getByLabel("Логин", { exact: true }).fill(process.env.E2E_LOGIN!);
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.E2E_PASSWORD!);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("button", { name: "Импорт документов", exact: true })).toBeVisible();

  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  let attempts = 0;
  await page.route("**/api/imports", async route => {
    attempts += 1;
    if (attempts === 1) {
      await pending;
      await route.fulfill({ status: 503, contentType: "application/json",
        body: JSON.stringify({ detail: "Архив временно недоступен" }) });
    } else if (attempts === 2) {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    } else {
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify([{ id: "anonymous-document", filename: "Проверка архива.xlsx",
          kind: "kug", at: "2026-10-09T00:00:00Z" }]) });
    }
  });

  await page.getByRole("button", { name: "Импорт документов", exact: true }).click();
  try {
    await expect(page.getByRole("status")).toHaveText("Загружаем список документов…");
    await expect(page.getByText("Документы ещё не загружены.", { exact: true })).toHaveCount(0);
  } finally {
    release();
  }
  await expect(page.getByText("Архив временно недоступен", { exact: true })).toBeVisible();
  await expect(page.getByText("Документы ещё не загружены.", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Повторить загрузку", exact: true }).click();
  await expect(page.getByText("Документы ещё не загружены.", { exact: true })).toBeVisible();
  await expect(page.getByText("Архив временно недоступен", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Расписание", exact: true }).click();
  await page.getByRole("button", { name: "Импорт документов", exact: true }).click();
  await expect(page.getByText("Проверка архива.xlsx", { exact: true })).toBeVisible();
  await expect(page.getByText("Документы ещё не загружены.", { exact: true })).toHaveCount(0);
  expect(attempts).toBe(3);
});

test("saved college confirmation differs from unsaved settings edits", async ({ page }) => {
  test.skip(!process.env.E2E_LOGIN || !process.env.E2E_PASSWORD,
    "Use the disposable CI environment, never a production workspace");
  await page.goto("/");
  await page.getByLabel("Логин", { exact: true }).fill(process.env.E2E_LOGIN!);
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.E2E_PASSWORD!);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("button", { name: "Настройки", exact: true })).toBeVisible();
  const original = await (await page.request.get("/api/state")).json();
  const me = await (await page.request.get("/api/auth/me")).json();
  const headers = { "X-CSRF-Token": me.csrf };
  const settings = { ...original.state.settings, confirmed: true };
  try {
    const saved = await page.request.put("/api/settings", {
      headers, data: { version: original.version, item: settings },
    });
    expect(saved.ok()).toBeTruthy();
    await page.reload();
    await page.getByRole("button", { name: "Настройки", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Правила подтверждены", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Сначала подтвердите правила", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Сохранить настройки", exact: true })).toBeDisabled();
    await page.getByLabel("Название рабочего пространства", { exact: true }).fill("Несохранённый черновик");
    await expect(page.getByText("Изменения формы начнут действовать после сохранения.", { exact: true })).toBeVisible();
    expect((await (await page.request.get("/api/state")).json()).state.settings.name).toBe(settings.name);
  } finally {
    const current = await (await page.request.get("/api/state")).json();
    const restored = await page.request.post(`/api/history/${original.version}/restore`, {
      headers, data: { version: current.version },
    });
    expect(restored.ok()).toBeTruthy();
  }
});
