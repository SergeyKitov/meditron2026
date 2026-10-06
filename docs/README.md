# Документация Patient pathway

Начните с [запуска](run.md) и [текущего состояния реализации](implementation-status.md). [Архитектура](architecture.md) описывает границы продукта, а [цикл одного шага](next-step-cycle.md) — основной процесс.

| Задача | Документ |
| --- | --- |
| Понять модель и её ограничения | [Маршрутизация CatBoost](model-routing.md), [протокол оценки](evaluation-protocol.md), [результаты на синтетических сценариях](evaluation-results-synthetic.json) |
| Подключить учреждение | [Настройка профиля](configuration-guide.md), [вход заключений](report-ingress-contract.md), [статусы записи](booking-feedback-contract.md) |
| Подготовить демонстрацию | [Сценарии и контракты](synthetic-demo-and-contracts.md), [каталог причин](tag-catalog.md), [материалы питча](pitch/README.md) |
| Проверить источники и развитие | [Источники для матрицы](research-and-matrix-inputs.md), [правки специалиста](quality-loop.md), [стек](technology-stack.md), [комплект к защите](submission-checklist.md) |

`tag.source.json` хранит исходную таблицу пользователя; `tag.json` — сокращённый рабочий каталог. Исполняемые настройки и модель находятся в `config/`, код и тесты — в `backend/`, `frontend/` и `scripts/`.
