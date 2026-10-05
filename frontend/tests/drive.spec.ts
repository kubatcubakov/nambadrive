import { test, expect, type Page } from "@playwright/test";
const id = "11111111-1111-4111-8111-111111111111";
const doc = {
  id,
  name: "Договор поставки.txt",
  resource_type: "DOCUMENT",
  department_id: id,
  department_name: "Финансы",
  owner_user_id: id,
  owner_name: "Айгуль",
  size: 24,
  favorite: false,
};
async function fixture(page: Page, admin = false) {
  let favorite = false;
  const user = {
    id,
    display_name: "Айгуль",
    username: "aigul",
    email: "aigul@example.test",
    enabled: true,
  };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let data: unknown = [];
    if (path === "/api/v1/auth/me") data = user;
    else if (path === "/api/v1/auth/csrf")
      data = { csrf_token: "ui-test-only" };
    else if (path === "/api/v1/drive/capabilities")
      data = { administration: admin, organization: admin };
    else if (path === "/api/v1/drive")
      data =
        url.searchParams.get("view") === "favorites" && !favorite
          ? []
          : [{ ...doc, favorite }];
    else if (path === "/api/v1/favorites/" + id) {
      favorite = route.request().method() === "PUT";
      data = { favorite };
    } else if (path === "/api/v1/documents/" + id)
      data = {
        ...doc,
        classification: "INTERNAL",
        inherit_acl: true,
        mime_type: "text/plain",
        sha256: "a".repeat(64),
        metadata: { description: "Согласованный договор", tags: ["договор"] },
      };
    else if (path === "/api/v1/resources/" + id + "/capabilities")
      data = ["VIEW", "PREVIEW"];
    else if (path === "/api/v1/notifications/preferences")
      data = { email_enabled: true };
    else if (path === "/api/v1/quotas/me")
      data = { used_bytes: 24, limit_bytes: 1024 };
    else if (path === "/api/v1/quotas/capabilities") data = { manage: false };
    else if (path === "/api/v1/admin/dashboard")
      data = {
        enabled_users: 8,
        quarantined_versions: 2,
        pending_transfers: 0,
        logical_bytes: 1024,
      };
    await route.fulfill({ json: { data } });
  });
}

test("reader navigation, favorites and download UI follow backend capabilities", async ({
  page,
}, info) => {
  await fixture(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Мои документы" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Администрирование", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "В избранное", exact: true }).click();
  await page.getByRole("button", { name: "Избранное", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Договор поставки.txt" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Договор поставки.txt" }).click();
  await expect(
    page.getByRole("heading", { name: "Договор поставки.txt" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Скачать", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Открыть в редакторе" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Предпросмотр", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("desktop.png"),
    fullPage: true,
  });
});

test("admin dashboard is separated from content", async ({ page }) => {
  await fixture(page, true);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Администрирование", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Состояние NambaDrive" }),
  ).toBeVisible();
  await expect(
    page.getByText("Активные пользователи", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Договор поставки.txt" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Мои документы", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Договор поставки.txt" }),
  ).toBeVisible();
});

test("mobile layout and revoked document do not retain stale detail", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Договор поставки.txt" }).click();
  await expect(
    page.getByRole("heading", { name: "Договор поставки.txt" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: info.outputPath("mobile.png"),
    fullPage: true,
  });
  await page.route("**/api/v1/documents/" + id, (route) =>
    route.fulfill({
      status: 403,
      json: { error: { message: "Access denied" } },
    }),
  );
  await page.getByRole("button", { name: "Договор поставки.txt" }).click();
  await expect(
    page.getByRole("heading", { name: "Договор поставки.txt" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Операция недоступна: проверьте права и данные"),
  ).toBeVisible();
});
