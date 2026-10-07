import { test, expect } from "@playwright/test";

test("self study import, schedule, responsible teacher, manual preservation and college profile", async ({
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
  const end = new Date(`${week}T12:00:00`);
  end.setDate(end.getDate() + 6);
  try {
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
    await modal
      .getByLabel("Подтверждённое окончание семестра")
      .fill(end.toISOString().slice(0, 10));
    const entry = modal
      .locator("[data-source-key]")
      .filter({ hasText: "С/Р для проверки Word" });
    await entry.locator("summary").click();
    await entry
      .getByLabel("Названия групп через ;")
      .fill(before.state.groups.g1.name);
    await entry
      .getByLabel("ФИО преподавателей через ;")
      .fill(before.state.teachers.t1.name);
    await entry
      .getByLabel("Преподаватель присутствует", { exact: true })
      .uncheck();
    await entry.getByLabel("Включить после проверки").check();
    await modal
      .getByLabel("Я проверил даты семестра", { exact: false })
      .check();
    await modal
      .getByRole("button", {
        name: "Сохранить семестровые назначения",
        exact: true,
      })
      .click();
    await expect(modal).not.toBeVisible();
    const confirmed = await (await page.request.get("/api/state")).json();
    const allocation: any = Object.values(confirmed.state.allocations).find(
      (a: any) => a.kind === "self_study",
    );
    expect(allocation.hours).toBe(4);
    expect(allocation.teacher_ids).toEqual(["t1"]);
    expect(allocation.teacher_presence).toBe(false);
    await page
      .getByRole("navigation")
      .getByRole("button", { name: /^Нагрузка/ })
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
      .getByLabel("Всего академических часов", { exact: true })
      .fill("4");
    await edit.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(edit).not.toBeVisible();
    await page.getByRole("button", { name: "Расписание", exact: true }).click();
    const generate = async () => {
      await page
        .getByRole("button", { name: "Сформировать", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Запустить расчёт", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Применить вариант", exact: true })
        .click({ timeout: 20000 });
    };
    await generate();
    const scheduled = await (await page.request.get("/api/state")).json();
    const self: any = Object.values(scheduled.state.lessons).find(
      (l: any) => l.kind === "self_study",
    );
    expect(self.teacher_ids).toEqual(["t1"]);
    expect(self.room_id).toBeNull();
    await page.locator(`[data-lesson-id="${self.id}"]`).first().click();
    const lesson = page.getByRole("dialog", { name: "Редактирование занятия" });
    await expect(
      lesson.getByLabel("Закрепить при повторной генерации"),
    ).toBeChecked();
    await lesson
      .getByLabel("Комментарий", { exact: true })
      .fill("Сохранить ручную правку С/Р");
    await lesson
      .getByRole("button", { name: "Сохранить", exact: true })
      .click();
    await expect(lesson).not.toBeVisible();
    await generate();
    const regenerated = await (await page.request.get("/api/state")).json();
    expect(regenerated.state.lessons[self.id].note).toBe(
      "Сохранить ручную правку С/Р",
    );
    await page.getByRole("button", { name: "Проверить", exact: true }).click();
    await expect(
      page.getByText(
        "Все плановые часы размещены, обязательные проверки пройдены.",
      ),
    ).toBeVisible();
    await page.getByRole("button", { name: "Закрыть", exact: true }).click();
    await page.getByRole("button", { name: "Настройки", exact: true }).click();
    await page
      .getByRole("button", {
        name: "Загрузить согласованные правила колледжа",
        exact: true,
      })
      .click();
    await expect(page.getByLabel("Минут в академическом часе")).toHaveValue(
      "45",
    );
    await expect(
      page.getByLabel("Недельный норматив, включая С/Р"),
    ).toHaveValue("36");
    await expect(page.getByLabel("Максимум часов группы в день")).toHaveValue(
      "10",
    );
    await expect(page.getByLabel("end пары 1", { exact: true })).toHaveValue(
      "10:05",
    );
    await expect(
      page.getByLabel("break_minutes пары 1", { exact: true }),
    ).toHaveValue("5");
    await page.screenshot({
      path: "test-results/college-profile.png",
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    const current = await (await page.request.get("/api/state")).json();
    const me = await (await page.request.get("/api/auth/me")).json();
    const restore = await page.request.post(
      `/api/history/${before.version}/restore`,
      {
        headers: { "X-CSRF-Token": me.csrf },
        data: { version: current.version },
      },
    );
    expect(restore.ok()).toBeTruthy();
  }
});
