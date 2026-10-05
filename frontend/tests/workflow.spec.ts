import { test, expect } from "@playwright/test";

test("demo profiles isolate their screens and specialist can leave a request", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".case-list")).toBeVisible();
  await expect(page.locator(".detail")).not.toBeVisible();
  await page.locator(".case-card").first().click();
  await expect(page.locator(".case-list")).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Все заявки на валидацию" })).toBeVisible();
  await page.getByRole("button", { name: "Все заявки на валидацию" }).click();
  await expect(page.locator(".case-list")).toBeVisible();
  await page.getByRole("button", { name: "Добавить исследование" }).click();
  await expect(page.getByRole("dialog", { name: "Новое исследование" })).toBeVisible();
  await page.getByRole("button", { name: "Пациент", exact: true }).evaluate((button) => (button as HTMLButtonElement).click());
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "Ваш следующий шаг" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Добавить исследование" })).not.toBeVisible();
  await page.getByRole("button", { name: "Администратор", exact: true }).click();
  await expect(page.getByRole("tab", { name: "История" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Воронка" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Подтвердить маршрут" })).not.toBeVisible();
});

test("CT demo shows no next step, consultation, and specialist-added lab preparation", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Добавить исследование" }).click();
  await page.getByLabel("Исследование", { exact: true }).selectOption("CT_CHEST");
  await page.getByLabel("Ситуация").selectOption("normal");
  await page.getByRole("button", { name: "Создать исследование" }).click();
  await expect(page.getByText("КТ ОГК: лёгочные узлы не выявлены.")).toBeVisible();
  await expect(page.getByText("Модель не предлагает нового шага.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить маршрут" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(page.getByText("По текущему заключению новый шаг не назначен")).toBeVisible();
  await expect(page.getByRole("button", { name: "Записаться", exact: true })).not.toBeVisible();

  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await page.getByRole("button", { name: "Добавить исследование" }).click();
  await page.getByLabel("Исследование", { exact: true }).selectOption("CT_CHEST");
  await page.getByLabel("Ситуация").selectOption("finding");
  await page.getByRole("button", { name: "Создать исследование" }).click();
  await expect(page.getByRole("heading", { name: "Консультация пульмонолога по находке на КТ" })).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить маршрут" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(page.getByRole("button", { name: "Записаться", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await page.getByRole("button", { name: "Добавить исследование" }).click();
  await page.getByLabel("Исследование", { exact: true }).selectOption("CT_CHEST");
  await page.getByLabel("Ситуация").selectOption("multiple_with_lab");
  await page.getByRole("button", { name: "Создать исследование" }).click();
  await expect(page.getByRole("dialog", { name: "Изменение маршрута" })).toBeVisible();
  await expect(page.getByText("Модель его не выбирала.", { exact: false })).toBeVisible();
  await expect(page.getByLabel("Название анализа")).toHaveValue("Анализ по решению специалиста");
  await page.getByRole("button", { name: "Сохранить и подтвердить" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Анализ по решению специалиста" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Записаться на анализ" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Записаться", exact: true })).toBeVisible();
});

test("review, book, receive result, then approve one linked next step", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Заявки на валидацию" }),
  ).toBeVisible();
  await page.locator(".case-card").first().click();
  await expect(
    page.getByRole("button", { name: "Подтвердить маршрут" }),
  ).toBeEnabled();
  await page.screenshot({ path: "test-results/reviewer.png", fullPage: true });
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Специалист рассматривает результат" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await page.getByRole("button", { name: "Изменить маршрут" }).click();
  await page
    .getByLabel("Следующий шаг", { exact: true })
    .fill("Консультация по результату исследования");
  await page
    .getByLabel("Причина решения")
    .fill("Уточнено название консультации для пациента");
  await page.getByLabel("Категория причины").selectOption("wording");
  await page.getByRole("button", { name: "Сохранить и подтвердить" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(
    page.getByText("Подтверждено специалистом", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Повторная консультация по результату" }),
  ).not.toBeVisible();
  await page.getByRole("button", { name: "Записаться", exact: true }).click();
  await expect(page.getByText("Вы записаны", { exact: false })).toBeVisible();
  await expect(page.getByText("Запись подтверждена симулятором")).toBeVisible();
  await page.screenshot({ path: "test-results/patient.png", fullPage: true });
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await page.getByRole("button", { name: "Загрузить результат" }).click();
  await expect(
    page.getByRole("button", { name: "Загрузить результат" }),
  ).not.toBeVisible();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Повторная консультация по результату" }),
  ).not.toBeVisible();
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await expect(page.getByText("Автоматический путь не выбран.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Изменить маршрут" }).click();
  await page.getByLabel("Следующий шаг", { exact: true }).fill("Повторная консультация по результату");
  await page.getByLabel("Причина решения").fill("Получен результат первого приёма");
  await page.getByLabel("Категория причины").selectOption("route_logic");
  await page.getByRole("button", { name: "Сохранить и подтвердить" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Повторная консультация по результату" })).toBeVisible();
  await page
    .getByRole("button", { name: "Нужна помощь с выбором времени" })
    .click();
  await expect(
    page.getByText("Координатор поможет подобрать время.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Администратор", exact: true }).click();
  await page.getByRole("tab", { name: "История", exact: true }).click();
  await expect(
    page.getByText("Уточнено название консультации для пациента", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Администратор", exact: true }).click();
  await page.getByRole("tab", { name: "Воронка" }).click();
  await expect(
    page.getByText("Конверсия из показа версии маршрута", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Проект → решение специалиста", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Где специалист меняет проект модели" }),
  ).toBeVisible();
  await expect(page.getByText("Изменён текст: 1").first()).toBeVisible();
  expect(browserErrors).toEqual([]);
});

test("SR with unknown purpose requires manual choice; correction requires another approval", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Добавить исследование" }).click();
  await page.getByLabel("Профиль подключения").selectOption("pacs");
  await page
    .getByLabel("Исследование", { exact: true })
    .selectOption("CT_CHEST");
  await page.getByLabel("Назначение исследования").selectOption("unknown");
  await page.getByRole("button", { name: "Создать исследование" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "Подтвердить маршрут" }),
  ).toBeDisabled();
  await expect(page.getByText("ТЕКУЩИЙ ПРИЁМ · DICOM SR")).toBeVisible();
  await page.getByRole("button", { name: "Изменить маршрут" }).click();
  await page
    .getByRole("button", { name: "Один следующий шаг", exact: true })
    .click();
  await page
    .getByLabel("Причина решения")
    .fill("Демонстрационное ручное решение");
  await page
    .getByLabel("Категория причины")
    .selectOption("insufficient_context");
  await page.getByRole("button", { name: "Сохранить и подтвердить" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Записаться", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await page
    .getByRole("button", { name: "Демо: получить исправленное заключение" })
    .click();
  await expect(
    page.getByRole("button", { name: "Подтвердить маршрут" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Записаться", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("Получены новые данные.", { exact: false }),
  ).toBeVisible();
});

test("patient can decline a step, reconsider and book it", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Добавить исследование" }).click();
  await page.getByRole("button", { name: "Создать исследование" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Подтвердить маршрут" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(page.getByRole("button", { name: "Записаться", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Отказаться от шага" })).toBeDisabled();
  await page.getByLabel("Если не планируете этот шаг, укажите причину").selectOption("no_time");
  await page.getByRole("button", { name: "Отказаться от шага" }).click();
  await expect(page.getByText("Вы отказались от этого шага")).toBeVisible();
  await expect(page.getByRole("button", { name: "Записаться", exact: true })).not.toBeVisible();
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await expect(page.getByText("Пациент отказался от шага", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await page.getByRole("button", { name: "Вернуться к записи" }).click();
  await expect(page.getByRole("button", { name: "Записаться", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Завтра, 11:30" }).click();
  await page.getByRole("button", { name: "Записаться", exact: true }).click();
  await expect(page.getByText("Вы записаны", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Администратор", exact: true }).click();
  await page.getByRole("tab", { name: "Воронка" }).click();
  await expect(page.getByText("Пациент отказался от шага")).toBeVisible();
  await expect(page.getByText("Пациент вернулся к шагу")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Выбор пациента после показа" })).toBeVisible();
  await expect(page.getByText("Не подходит время — 1")).toBeVisible();
});

test("lab preparation and main booking proceed in parallel", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Добавить исследование" }).click();
  await page.getByRole("button", { name: "Создать исследование" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Изменить маршрут" }).click();
  await page.getByRole("button", { name: "Добавить анализ" }).click();
  await page.getByLabel("Название анализа").fill("Синтетический анализ перед услугой");
  await page.getByLabel("Причина решения").fill("Подготовка по демонстрационному протоколу услуги");
  await page.getByLabel("Категория причины").selectOption("route_logic");
  await page.getByRole("button", { name: "Сохранить и подтвердить" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Синтетический анализ перед услугой" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Записаться", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Записаться", exact: true }).click();
  await page.getByRole("button", { name: "Записаться на анализ" }).click();
  await expect(page.getByText("Анализ запланирован:", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await expect(page.getByRole("button", { name: "Загрузить результат" })).toBeDisabled();
  await page.getByRole("button", { name: "Результат готов и принят" }).click();
  await expect(page.getByRole("button", { name: "Загрузить результат" })).toBeEnabled();
  await page.getByRole("button", { name: "Загрузить результат" }).click();
  await expect(page.getByText("Автоматический путь не выбран.", { exact: false })).toBeVisible();
});

test("rejected proposal can be corrected and published during the same visit", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Добавить исследование" }).click();
  await page.getByRole("button", { name: "Создать исследование" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Изменить маршрут" }).click();
  await page.getByLabel("Причина решения").fill("Нужно исправить последовательность");
  await page.getByLabel("Категория причины").selectOption("route_logic");
  await page.getByRole("button", { name: "Отклонить проект" }).click();
  await expect(page.getByText("Версия 2")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Подтвердить маршрут" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Специалист рассматривает результат" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await page.getByRole("button", { name: "Изменить маршрут" }).click();
  await page.getByLabel("Следующий шаг", { exact: true }).fill("Исправленный первый шаг");
  await page.getByLabel("Причина решения").fill("Исправлен маршрут после отклонения");
  await page.getByLabel("Категория причины").selectOption("route_logic");
  await page.getByRole("button", { name: "Сохранить и подтвердить" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Исправленный первый шаг" })).toBeVisible();
  await page.getByRole("button", { name: "Администратор", exact: true }).click();
  await page.getByRole("tab", { name: "История", exact: true }).click();
  await expect(page.getByText("v1 · Отклонён", { exact: false })).toBeVisible();
});

test("small screen has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator(".case-card").first()).toBeVisible();
  await page.locator(".case-card").first().click();
  await expect(page.locator(".detail-title")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
});

test("deferred clinic booking appears only after feedback", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Добавить исследование" }).click();
  await page.getByLabel("Профиль подключения").selectOption("pacs");
  await page
    .getByLabel("Исследование", { exact: true })
    .selectOption("CT_CHEST");
  await page.getByRole("button", { name: "Создать исследование" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Подтвердить маршрут" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Записаться", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Записаться", exact: true }).click();
  await expect(page.getByText("Запрос на запись отправлен")).toBeVisible();
  await expect(
    page.getByText("Запрос передан. Ожидаем подтверждения времени."),
  ).toBeVisible();
  await expect(page.getByText("Вы записаны")).not.toBeVisible();
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await page.getByRole("button", { name: "Подтвердить слот" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(page.getByText("Вы записаны")).toBeVisible();
  await page.getByRole("button", { name: "Отменить запись" }).click();
  await expect(page.getByText("Отмена ожидает подтверждения")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Записаться", exact: true }),
  ).not.toBeVisible();
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await page.getByRole("button", { name: "Подтвердить отмену" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Записаться", exact: true }),
  ).toBeVisible();
});

test("specialist carries a booking into a revised matching route", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Добавить исследование" }).click();
  await page.getByRole("button", { name: "Создать исследование" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  const casesResponse = await page.request.get("/api/v1/cases", {
    headers: { "X-Demo-Role": "reviewer" },
  });
  const caseId = (await casesResponse.json())[0].id as string;
  await page.getByRole("button", { name: "Подтвердить маршрут" }).click();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await page.getByRole("button", { name: "Завтра, 15:00" }).click();
  await page.getByRole("button", { name: "Записаться", exact: true }).click();
  await expect(page.getByText("Вы записаны", { exact: false })).toBeVisible();
  const revision = await page.request.post(
    `/api/v1/cases/${caseId}/demo-revision`,
    {
      headers: {
        "X-Demo-Role": "reviewer",
        "Idempotency-Key": `matching-revision-${Date.now()}`,
      },
      data: {
        profile_id: "private",
        modality: "MAMMOGRAPHY",
        scenario: "finding",
        exam_purpose: "diagnostic",
      },
    },
  );
  expect(revision.ok()).toBe(true);
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Подтвердить маршрут" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Подтвердить маршрут" }).click();
  await expect(
    page.getByRole("button", { name: "Сохранить в новом маршруте" }),
  ).toBeVisible();
  await page
    .getByPlaceholder("Причина сохранения записи")
    .fill("Подтверждено соответствие услуги новому маршруту");
  await page
    .getByRole("button", { name: "Сохранить в новом маршруте" })
    .click();
  await expect(
    page.getByText("Существующая запись сохранена в текущем маршруте"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Пациент", exact: true }).click();
  await expect(page.getByText("Ранее оформленные записи")).not.toBeVisible();
  await expect(page.getByText("Вы записаны", { exact: false })).toBeVisible();
});
