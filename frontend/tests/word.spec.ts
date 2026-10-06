import { test, expect } from "@playwright/test";

test("Word review, period assignment, weekly link and semester hour cap", async ({
  page,
}) => {
  test.skip(
    !process.env.E2E_LOGIN ||
      !process.env.E2E_PASSWORD ||
      !process.env.E2E_WORD_FILE,
    "Use disposable credentials and anonymous Word fixture",
  );
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("Логин", { exact: true }).fill(process.env.E2E_LOGIN!);
  await page
    .getByLabel("Пароль", { exact: true })
    .fill(process.env.E2E_PASSWORD!);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Импорт документов", exact: true }),
  ).toBeVisible();
  const before = await (await page.request.get("/api/state")).json();
  const week = before.state.requirements.n1.week;
  await page
    .getByRole("button", { name: "Импорт документов", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Семестровая нагрузка Word", exact: true })
    .click();
  await page
    .locator('input[type="file"]')
    .setInputFiles(process.env.E2E_WORD_FILE!);
  const modal = page.getByRole("dialog", {
    name: "Проверка семестровой нагрузки Word",
  });
  await expect(modal).toBeVisible();
  await modal.getByLabel("Подтверждённое начало семестра").fill(week);
  await modal.getByLabel("Подтверждённое окончание семестра").fill(week);
  const entry = modal.locator("[data-source-key]").first();
  await entry.locator("summary").click();
  await entry
    .getByLabel("Названия групп через ;")
    .fill(before.state.groups.g1.name);
  await entry
    .getByLabel("ФИО преподавателей через ;")
    .fill(before.state.teachers.t1.name);
  await entry.getByLabel("Включить после проверки").check();
  await modal.getByLabel("Я проверил даты семестра", { exact: false }).check();
  await modal
    .getByRole("button", {
      name: "Сохранить семестровые назначения",
      exact: true,
    })
    .click();
  await expect(modal).not.toBeVisible();
  const confirmed = await (await page.request.get("/api/state")).json();
  expect(Object.keys(confirmed.state.requirements).length).toBe(
    Object.keys(before.state.requirements).length,
  );
  const allocation: any = Object.values(confirmed.state.allocations).find(
    (a: any) =>
      confirmed.state.subjects[a.subject_id].name ===
      "Раздел для проверки Word",
  );
  expect(allocation.hours).toBe(4);
  await page
    .getByRole("navigation")
    .getByRole("button", { name: /^Нагрузка/ })
    .click();
  await page.getByRole("button", { name: /Семестровая нагрузка ·/ }).click();
  await expect(
    page.getByText("Раздел для проверки Word", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Недельный план", exact: true })
    .click();
  await page
    .locator("main")
    .getByRole("button", { name: "Нагрузка", exact: true })
    .click();
  const edit = page.getByRole("dialog", { name: "Новая нагрузка" });
  await edit
    .getByLabel("Семестровое назначение", { exact: true })
    .selectOption(allocation.id);
  await edit
    .getByRole("checkbox", { name: before.state.rooms.r1.name, exact: true })
    .check();
  await edit.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(edit).not.toBeVisible();
  const linked = await (await page.request.get("/api/state")).json();
  const req: any = Object.values(linked.state.requirements).find(
    (r: any) => r.allocation_id === allocation.id,
  );
  expect(req.hours).toBe(2);
  const row = page.locator("tr").filter({
    has: page.getByText("Раздел для проверки Word", { exact: true }),
  });
  await row
    .getByRole("button", { name: "Редактировать нагрузку", exact: true })
    .click();
  const change = page.getByRole("dialog", { name: "Редактирование нагрузки" });
  await change
    .getByLabel("Всего академических часов", { exact: true })
    .fill("5");
  await change.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(change.getByText(/превышают семестровые/)).toBeVisible();
  expect((await (await page.request.get("/api/state")).json()).version).toBe(
    linked.version,
  );
  await change.getByRole("button", { name: "Отмена", exact: true }).click();
  if (process.env.E2E_REAL_WORD_FILES) {
    await page
      .getByRole("button", { name: "Импорт документов", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Семестровая нагрузка Word", exact: true })
      .click();
    for (const file of JSON.parse(
      process.env.E2E_REAL_WORD_FILES,
    ) as string[]) {
      await page.locator('input[type="file"]').setInputFiles(file);
      await expect(modal).toBeVisible();
      await expect(
        modal.getByLabel("Таблица / семестр").locator("option"),
      ).toHaveCount(file.split("/").pop()!.startsWith("11") ? 6 : 2);
      const source = modal.locator("[data-source-key]").first();
      await source.locator("summary").click();
      await expect(source.locator(".source-cell")).toBeVisible();
      await modal.getByRole("button", { name: "Отмена", exact: true }).click();
    }
  }
  expect(errors).toEqual([]);
});
