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
  expect((await page.getByRole("heading",{name:"Договор поставки.txt"}).boundingBox())?.y).toBeLessThan(250);
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
  await page.getByRole("button", { name: "Обновить документ", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Договор поставки.txt" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Операция недоступна: проверьте права и данные"),
  ).toBeVisible();
});

test("organization uses named choices and submits the existing assignment contract", async ({ page }, info) => {
  await fixture(page, true);
  let assignment: unknown;
  await page.route("**/api/v1/admin/organization**", async route => {
    if (route.request().method() === "PUT") assignment = route.request().postDataJSON();
    await route.fulfill({json:{data:{companies:[{id,name:"NAMBAGROUP"}],departments:[{id,name:"IT",company_id:id,parent_id:null}],department_memberships:[{user_id:id,department_id:id,kind:"SECONDARY"}],department_managers:[]}}});
  });
  await page.route("**/api/v1/identity", route=>route.fulfill({json:{data:{users:[{id,display_name:"Айгуль",enabled:true}]}}}));
  await page.goto("/");
  await page.getByRole("button",{name:"Администрирование",exact:true}).click();
  await page.getByRole("button",{name:"Организация",exact:true}).click();
  await page.getByRole("button",{name:"▰ IT",exact:true}).click();
  await expect(page.getByRole("cell",{name:"Дополнительный отдел"})).toBeVisible();
  await page.getByLabel("Сотрудник",{exact:true}).selectOption(id);
  const request=page.waitForRequest(r=>r.url().endsWith(`/departments/${id}/assignments`) && r.method()==="PUT");
  await page.getByRole("button",{name:"Назначить",exact:true}).click();
  const sent=await request;
  expect(sent.headers()["x-csrf-token"]).toBe("ui-test-only");
  await expect(page.getByRole("status")).toHaveText("Изменения сохранены");
  expect(assignment).toEqual({user_id:id,kind:"SECONDARY",valid_until:null});
  await page.getByRole("button",{name:"Структура",exact:true}).click();
  await expect(page.getByRole("button",{name:"Создать отдел",exact:true})).toBeDisabled();
  await page.screenshot({path:info.outputPath("organization.png"),fullPage:true});
});

test("folder upload is distinct from a new version and unsupported office preview is hidden", async ({page},info)=>{
  await fixture(page);
  const folder="22222222-2222-4222-8222-222222222222";
  const space={id:folder,name:"Документы IT",resource_type:"SPACE",department_id:id,owner_name:"Айгуль",department_name:"IT"};
  await page.route("**/api/v1/drive?*",r=>r.fulfill({json:{data:[space]}}));
  await page.route(`**/api/v1/resources?parent_id=${folder}`,r=>r.fulfill({json:{data:[{...doc,name:"Договор.docx"}]}}));
  await page.route(`**/api/v1/resources/${folder}/capabilities`,r=>r.fulfill({json:{data:["VIEW","CREATE","CREATE_FOLDER"]}}));
  await page.route(`**/api/v1/resources/${id}/capabilities`,r=>r.fulfill({json:{data:["VIEW","PREVIEW","EDIT","UPLOAD_NEW_VERSION","VIEW_VERSION_HISTORY"]}}));
  await page.route(`**/api/v1/documents/${id}`,r=>r.fulfill({json:{data:{...doc,name:"Договор.docx",mime_type:"application/vnd.openxmlformats-officedocument.wordprocessingml.document",metadata:{},classification:"INTERNAL",inherit_acl:true}}}));
  await page.route("**/api/v1/documents/upload?*",r=>r.fulfill({json:{data:{status:"PENDING"}}}));
  await page.goto("/");
  await page.getByRole("button",{name:"Документы IT",exact:false}).click();
  await page.getByRole("button",{name:"Загрузить файлы",exact:true}).click();
  await page.getByLabel("Выберите файл").setInputFiles({name:"проверка.txt",mimeType:"text/plain",buffer:Buffer.from("Test")});
  const upload=page.waitForRequest(r=>r.url().includes("/documents/upload?") && r.method()==="POST");
  await page.getByRole("button",{name:"Загрузить",exact:true}).click();
  expect(new URL((await upload).url()).searchParams.get("parent_id")).toBe(folder);
  await expect(page.getByText("Принято файлов: 1. Они появятся в папке после антивирусной проверки.")).toBeVisible();
  await page.screenshot({path:info.outputPath("file-list.png"),fullPage:true});
  await page.getByRole("button",{name:"Договор.docx",exact:false}).click();
  await expect(page.getByRole("button",{name:"Загрузить файлы",exact:true})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"Договор.docx",exact:false})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"Предпросмотр",exact:true})).toHaveCount(0);
  await expect(page.getByRole("link",{name:"Открыть в редакторе",exact:true})).toBeVisible();
  await expect(page.getByRole("heading",{name:"Новая версия",exact:true})).not.toBeVisible();
  await expect(page.getByRole("navigation",{name:"Панель документа"})).not.toBeVisible();
  await expect(page.getByRole("link",{name:"Открыть в редакторе"})).toHaveAttribute("target","_blank");
  await expect(page.getByRole("link",{name:"Открыть в редакторе"})).toHaveAttribute("href",`/?editor=${id}`);
  await page.getByRole("button",{name:"Сведения, доступ и версии"}).click();
  await page.getByRole("button",{name:"Версии",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Новая версия",exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath("file-workspace.png"),fullPage:true});
});

test("global header search keeps the existing encoded API and clears results", async ({page})=>{
  await fixture(page);
  await page.route("**/api/v1/search?*",r=>r.fulfill({json:{data:[{...doc,snippet:"Согласованный договор"}]}}));
  await page.goto("/");
  const input=page.getByRole("searchbox").or(page.getByLabel("Поиск по имени и содержимому",{exact:true}));
  await input.fill("договор IT");
  const search=page.waitForRequest(r=>r.url().includes("/api/v1/search?"));
  await page.getByRole("button",{name:"Найти",exact:true}).click();
  expect(new URL((await search).url()).searchParams.get("q")).toBe("договор IT");
  await expect(page.getByText("Согласованный договор",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Очистить",exact:true}).click();
  await expect(input).toHaveValue("");
  await expect(page.getByText("Согласованный договор",{exact:true})).toHaveCount(0);
});

test("standalone editor keeps session authorization and omits the workspace sidebar", async ({page})=>{
  await fixture(page);
  let csrfHeader="";
  await page.route(`**/api/v1/office/${id}/session`,async r=>{
    csrfHeader=r.request().headers()["x-csrf-token"];
    await r.fulfill({status:403,json:{error:{message:"denied"}}});
  });
  await page.goto(`/?editor=${id}`);
  await expect(page.getByRole("status")).toContainText("Редактор недоступен");
  expect(csrfHeader).toBe("ui-test-only");
  await expect(page.getByRole("navigation",{name:"Основная навигация"})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"Вернуться к документу"})).toBeVisible();
  await page.getByRole("button",{name:"Вернуться к документу"}).click();
  await expect(page).toHaveURL(new RegExp(`document=${id}`));
});
