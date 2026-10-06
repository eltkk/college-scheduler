import { test, expect } from "@playwright/test";

// Requires a separate deployment with the anonymous demo state and disposable accounts.
test("login, generation, conflicts, catalogs, export and history", async ({
  page,
}) => {
  test.skip(
    !process.env.E2E_LOGIN || !process.env.E2E_PASSWORD,
    "Set disposable E2E credentials",
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByLabel("Логин", { exact: true }).fill(process.env.E2E_LOGIN!);
  await page
    .getByLabel("Пароль", { exact: true })
    .fill(process.env.E2E_PASSWORD!);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("button", { name: "Сформировать", exact: true }).click();
  await page
    .getByRole("button", { name: "Запустить расчёт", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Применить вариант", exact: true })
    .click({ timeout: 20000 });
  await page.getByRole("button", { name: "Проверить", exact: true }).click();
  await expect(
    page.getByText(
      "Все плановые часы размещены, обязательные проверки пройдены.",
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();

  const before = await (await page.request.get("/api/state")).json();
  const lessons = Object.values(before.state.lessons) as any[];
  for (const l of lessons)
    await expect(
      page.locator(`[data-lesson-id="${l.id}"]`).first(),
    ).toBeVisible();
  const l = lessons[0];
  const time = (n: number) =>
    `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;
  await page.getByRole("button", { name: "Занятие", exact: true }).click();
  const modal = page.getByRole("dialog");
  await modal
    .getByLabel("Дисциплина", { exact: true })
    .selectOption(l.subject_id);
  await modal.getByLabel("Дата", { exact: true }).fill(l.day);
  await modal.getByLabel("Начало", { exact: true }).fill(time(l.start));
  await modal.getByLabel("Окончание", { exact: true }).fill(time(l.end));
  await modal
    .getByLabel("Академических часов", { exact: true })
    .fill(String(l.hours));
  for (const id of l.group_ids)
    await modal
      .getByRole("checkbox", {
        name: before.state.groups[id].name,
        exact: true,
      })
      .check();
  for (const id of l.teacher_ids)
    await modal
      .getByRole("checkbox", {
        name: before.state.teachers[id].name,
        exact: true,
      })
      .check();
  await modal.getByLabel("Помещение", { exact: true }).selectOption(l.room_id);
  await modal.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(modal.getByText(/Пересечение/)).toBeVisible();
  expect((await (await page.request.get("/api/state")).json()).version).toBe(
    before.version,
  );
  await modal.getByRole("button", { name: "Отмена", exact: true }).click();

  await page.getByRole("button", { name: "Справочники", exact: true }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await page
    .getByLabel("ФИО преподавателя", { exact: true })
    .fill("Проверка браузера");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(
    page.getByText("Проверка браузера", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Учебный календарь" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Импорт документов", exact: true })
    .click();
  await expect(
    page.getByText("Выберите файл Excel", { exact: true }),
  ).toBeVisible();
  if (process.env.E2E_KUG_FILE) {
    await page
      .locator('input[type="file"]')
      .setInputFiles(process.env.E2E_KUG_FILE);
    await expect(
      page.getByRole("dialog", { name: "Проверка КУГ" }),
    ).toBeVisible();
    await expect(
      page.getByRole("dialog").getByLabel("Лист / курс"),
    ).toBeVisible();
    await expect(
      page
        .getByRole("dialog")
        .getByText("Сопоставление занятий", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Отмена", exact: true })
      .click();
  }
  await page.getByRole("button", { name: "История", exact: true }).click();
  await expect(
    page.getByText("Сохранённые версии", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Расписание", exact: true }).click();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("link", { name: "Excel", exact: true }).click();
  expect((await downloaded).suggestedFilename()).toMatch(/^schedule-.*\.xlsx$/);
  await page.screenshot({ path: "test-results/schedule.png", fullPage: true });
  expect(errors).toEqual([]);
});
