import { test, expect } from "@playwright/test";

test("login makes copied spaces visible and sends exact corrected credentials", async ({ page }) => {
  let submitted: unknown;
  await page.route("**/api/auth/me", route => route.fulfill({ status: 401,
    contentType: "application/json", body: JSON.stringify({ detail: "Войдите" }) }));
  await page.route("**/api/auth/login", async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ status: 401, contentType: "application/json",
      body: JSON.stringify({ detail: "Неверный логин или пароль" }) });
  });
  await page.goto("/");
  const login = page.getByLabel("Логин", { exact: true });
  const password = page.getByLabel("Пароль", { exact: true });
  await expect(login).toHaveAttribute("autocapitalize", "none");
  await login.fill("Editor1");
  await password.fill(" anonymous-test-password ");
  await expect(page.getByRole("status")).toContainText("есть пробелы");
  await page.getByRole("button", { name: "Показать пароль", exact: true }).click();
  await expect(password).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Убрать пробелы по краям", exact: true }).click();
  await expect(password).toHaveValue("anonymous-test-password");
  await page.getByRole("button", { name: "Скрыть пароль", exact: true }).click();
  await expect(password).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByText("Неверный логин или пароль", { exact: true })).toBeVisible();
  expect(submitted).toEqual({ login: "Editor1", password: "anonymous-test-password" });
});
