import { test, expect } from "@playwright/test";

test("KUG week totals, college norm and mislabeled semester total", async ({ page }) => {
  test.skip(!process.env.E2E_LOGIN || !process.env.E2E_PASSWORD || !process.env.E2E_KUG_CHECK_FILE,
    "Set disposable E2E credentials and anonymous source-quality fixture");
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await page.getByLabel("Логин", { exact: true }).fill(process.env.E2E_LOGIN!);
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.E2E_PASSWORD!);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("button", { name: "Настройки", exact: true })).toBeVisible();
  const initial = await (await page.request.get("/api/state")).json();
  const auth = await (await page.request.get("/api/auth/me")).json();
  const headers = { "X-CSRF-Token": auth.csrf };
  try {
    const profile = await (await page.request.get("/api/settings/college-profile")).json();
    profile.confirmed = true;
    const changed = await page.request.put("/api/settings", {
      headers, data: { version: initial.version, item: profile },
    });
    expect(changed.ok()).toBeTruthy();
    await page.reload();
    await page.getByRole("button", { name: "Импорт документов", exact: true }).click();
    await page.locator('input[type="file"]').setInputFiles(process.env.E2E_KUG_CHECK_FILE!);
    const modal = page.getByRole("dialog", { name: "Проверка КУГ" });
    await expect(modal).toBeVisible();
    const week = modal.getByLabel("Столбец недели в исходнике");
    await modal.getByLabel("Реальная учебная неделя: понедельник").fill("2026-10-05");
    await expect(modal.getByText("36 академических часов", { exact: true })).toBeVisible();
    await week.selectOption("D:D");
    await expect(modal.getByText(/В исходном столбце 34 ч., норматив выбранной недели 36 ч./)).toBeVisible();
    await week.selectOption("E:E");
    await expect(modal.getByText(/В исходном столбце 38 ч., норматив выбранной недели 36 ч./)).toBeVisible();
    await week.selectOption("F:F");
    await expect(modal.getByText(/В столбце недели 612 ч./)).toBeVisible();
    await modal.getByRole("checkbox", { name: initial.state.groups.g1.name, exact: true }).check();
    await modal.getByRole("checkbox", { name: /Я проверил курс/ }).check();
    await expect(modal.getByRole("button", { name: "Подтвердить нагрузку", exact: true })).toBeDisabled();
    await week.selectOption("G:G");
    await expect(modal.getByText(/Сумма строк 36 ч. не совпадает с итогом исходного листа 40 ч./)).toBeVisible();
    await expect(modal.getByText("36 академических часов", { exact: true })).toBeVisible();
    expect((await (await page.request.get("/api/state")).json()).state.requirements).toEqual(initial.state.requirements);
    expect(errors).toEqual([]);
  } finally {
    const latest = await (await page.request.get("/api/state")).json();
    const restored = await page.request.post(`/api/history/${initial.version}/restore`, {
      headers, data: { version: latest.version },
    });
    expect(restored.ok()).toBeTruthy();
  }
});
