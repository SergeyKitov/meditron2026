import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type {
  Booking,
  CaseDetail,
  CaseSummary,
  IntegrationProfile,
  Metrics,
  Patient,
  QualityReview,
  Step,
} from "./types";
import "./styles.css";

const statusName: Record<string, string> = {
  draft: "На проверке",
  manual: "Нужно решение",
  approved: "Публикуется",
  published: "Подтверждён",
  superseded: "Заменён",
  rejected: "Отклонён",
  available: "Доступен",
  blocked: "После результата",
  completed: "Выполнен",
  not_needed: "Не требуется",
  confirmed: "Запись подтверждена",
  requested: "Запрос отправлен",
  awaiting_confirmation: "Ожидаем подтверждения",
  cancel_requested: "Ожидаем подтверждения отмены",
  cancelled: "Запись отменена",
  no_slots: "Помощь координатора",
};
const eventName: Record<string, string> = {
  result_received: "Получено заключение",
  route_proposed: "Подготовлен проект пути",
  approved: "Решение специалиста",
  published: "Маршрут опубликован",
  shown: "Пациент открыл маршрут",
  booking_requested: "Запрошена запись",
  booking_confirmed: "Запись подтверждена",
  step_declined: "Пациент отказался от шага",
  step_resumed: "Пациент вернулся к шагу",
  booking_submission_simulated: "Запрос передан",
  submit_booking_simulated: "Запрос подготовлен",
  booking_rejected: "Система записи отказала",
  action_completed: "Шаг выполнен",
  step_result_received: "Получен результат шага",
  prerequisite_result_received: "Получен результат подготовки",
  preparation_review_required: "Требуется повторная подготовка",
  cycle_closed: "Продолжение не требуется",
  notification_simulated: "Уведомление подготовлено",
  publish_route: "Передано на публикацию",
  route_rejected: "Маршрут отклонён",
  booking_cancelled: "Запись отменена",
  booking_cancellation_requested: "Запрошена отмена записи",
  booking_cancellation_submission_simulated: "Запрос отмены передан",
  booking_cancellation_rejected: "Система записи отказала в отмене",
  coordinator_task_created: "Задача координатору",
  booking_reconciliation_required: "Проверить прежнюю запись",
  booking_reconciled: "Прежняя запись сохранена в новом маршруте",
};
const reasonCodeName: Record<string, string> = {
  insufficient_context: "Недостаточно контекста",
  route_logic: "Логика маршрута",
  service_mapping: "Соответствие услуги",
  wording: "Формулировка",
  other: "Другая причина",
  unspecified: "Не указана",
};
const declineReasonName: Record<string, string> = {
  not_ready: "Пока не готов(а)",
  no_time: "Не подходит время",
  cost: "Стоимость",
  different_clinic: "Выбрал(а) другую клинику",
  other: "Другая причина",
};
const editTypeName: Record<string, string> = {
  route_changed: "Изменена структура пути",
  wording_only: "Изменён текст",
  no_effect: "Шаги не изменены",
};
const modality = (m: string) =>
  m === "MAMMOGRAPHY" ? "Маммография" : "КТ органов грудной клетки";
const examPurposeName: Record<string, string> = {
  screening: "скрининг",
  diagnostic: "диагностика",
  unknown: "назначение не указано",
};
const clinic = (p: string, profiles: Record<string, IntegrationProfile>) =>
  profiles[p]?.label ?? p;
const patientLabel = (caseId: string) => `Пациент P-${caseId.slice(0, 6).toUpperCase()}`;
const studyDate = (value: string) => new Date(value).toLocaleDateString("ru-RU");
const displayConclusion = (value: string) => value
  .replace(/\s*Синтетическое заключение\./g, "")
  .replace("Синтетический неполный результат маммографии.", "Неполный результат маммографии.");
const bookingReference = (value: string | null) => value ? value.replace(/^DEMO-/i, "") : "—";
const time = (s: string) =>
  s === "no-slots"
    ? "Помощь с записью"
    : `Завтра, ${s.replace("tomorrow-", "")}`;

async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  patientToken?: string,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Demo-Role": "reviewer",
  };
  if (method !== "GET") headers["Idempotency-Key"] = crypto.randomUUID();
  if (patientToken) headers["X-Patient-Token"] = patientToken;
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const data = await res.json();
  if (!res.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Проверьте заполненные поля",
    );
  return data;
}

const defaultSteps: Step[] = [
  {
    key: "review",
    title: "Обсудить результат со специалистом",
    description:
      "Специалист рассмотрит результат и определит дальнейшие действия.",
    action_type: "consultation",
    depends_on: [],
    unlock_on: [],
    prerequisites: [],
  },
];

const scenarioOptions: Record<string, { value: string; label: string }[]> = {
  CT_CHEST: [
    { value: "normal", label: "КТ · узлы не выявлены → без нового шага" },
    { value: "finding", label: "КТ · один узел → консультация" },
    { value: "multiple", label: "КТ · три узла → консультация" },
    { value: "multiple_with_lab", label: "КТ · три узла → врач добавляет анализ" },
  ],
  MAMMOGRAPHY: [
    { value: "normal", label: "Маммография · BI-RADS 1/2 → без нового шага" },
    { value: "followup", label: "Маммография · BI-RADS 3 → обсудить контроль" },
    { value: "finding", label: "Маммография · BI-RADS 4 → специалист" },
    { value: "priority", label: "Маммография · BI-RADS 5 → приоритетная консультация" },
    { value: "missing", label: "Маммография · поле отсутствует → ручной выбор" },
  ],
};

function Badge({ status }: { status: string }) {
  return (
    <span className={`badge ${status}`}>{statusName[status] ?? status}</span>
  );
}
function App() {
  const [profiles, setProfiles] = useState<Record<string, IntegrationProfile>>(
    {},
  );
  const [cases, setCases] = useState<CaseSummary[]>([]),
    [selected, setSelected] = useState(""),
    [detail, setDetail] = useState<CaseDetail | null>(null);
  const [tab, setTab] = useState<
    "reviewer" | "patient" | "timeline" | "metrics"
  >("reviewer");
  const [role, setRole] = useState<"reviewer" | "patient" | "admin">("reviewer");
  const [reviewerOpen, setReviewerOpen] = useState(false);
  const [patient, setPatient] = useState<Patient | null>(null),
    [metrics, setMetrics] = useState<Metrics | null>(null),
    [qualityReview, setQualityReview] = useState<QualityReview | null>(null);
  const [revision, setRevision] = useState(0),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [modal, setModal] = useState<"new" | "edit" | null>(null),
    [reason, setReason] = useState(""),
    [reasonCode, setReasonCode] = useState(""),
    [editedSteps, setEditedSteps] = useState<Step[]>([]);
  const [editingVersion, setEditingVersion] = useState(0);
  const [labPreset, setLabPreset] = useState(false);
  const [profile, setProfile] = useState("private"),
    [newModality, setNewModality] = useState("MAMMOGRAPHY"),
    [scenario, setScenario] = useState("finding"),
    [purpose, setPurpose] = useState("diagnostic");
  const [slots, setSlots] = useState<Record<string, string>>({}),
    [outcomes, setOutcomes] = useState<Record<string, string>>({});
  const [declineReasons, setDeclineReasons] = useState<Record<string, string>>({});
  const [reconcileReasons, setReconcileReasons] = useState<
    Record<string, string>
  >({});

  useEffect(() => {
    let stopped = false;
    const controller = new AbortController();
    api<Record<string, IntegrationProfile>>(
      "/profiles",
      "GET",
      undefined,
      undefined,
      controller.signal,
    )
      .then((loaded) => {
        if (stopped) return;
        setProfiles(loaded);
        setProfile((current) =>
          loaded[current]?.demo_scenarios
            ? current
            : (Object.entries(loaded).find(
                ([, value]) => value.demo_scenarios,
              )?.[0] ?? ""),
        );
      })
      .catch((cause) => {
        if (!stopped) setError((cause as Error).message);
      });
    return () => {
      stopped = true;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    let stopped = false;
    const controller = new AbortController();
    async function refresh() {
      try {
        const [list, stats, review] = await Promise.all([
          api<CaseSummary[]>(
            "/cases",
            "GET",
            undefined,
            undefined,
            controller.signal,
          ),
          api<Metrics>(
            "/metrics",
            "GET",
            undefined,
            undefined,
            controller.signal,
          ),
          api<QualityReview>(
            "/quality/rule-review",
            "GET",
            undefined,
            undefined,
            controller.signal,
          ),
        ]);
        if (!stopped) {
          setCases(list);
          setMetrics(stats);
          setQualityReview(review);
          if (!list.some((item) => item.id === selected)) {
            setSelected(list[0]?.id ?? "");
            setDetail(null);
            setPatient(null);
            setReviewerOpen(false);
            setError("");
          }
        }
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      }
    }
    refresh();
    const timer = setInterval(refresh, 2500);
    return () => {
      stopped = true;
      controller.abort();
      clearInterval(timer);
    };
  }, [revision, selected]);
  useEffect(() => {
    if (!selected) return;
    let stopped = false;
    const controller = new AbortController();
    async function refresh() {
      try {
        const value = await api<CaseDetail>(
          `/cases/${selected}`,
          "GET",
          undefined,
          undefined,
          controller.signal,
        );
        if (stopped) return;
        setDetail(value);
        const p = await api<Patient>(
          `/patient/cases/${selected}`,
          "GET",
          undefined,
          value.patient_token,
          controller.signal,
        );
        if (!stopped) setPatient(p);
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      }
    }
    refresh();
    const timer = setInterval(refresh, 1500);
    return () => {
      stopped = true;
      controller.abort();
      clearInterval(timer);
    };
  }, [selected, revision]);
  useEffect(() => {
    if (tab === "patient" && patient?.route && detail) {
      api(
        `/patient/cases/${detail.id}/shown`,
        "POST",
        undefined,
        detail.patient_token,
      ).catch(() => {});
    }
  }, [tab, patient?.route?.id, detail?.id]);

  async function act<T>(
    action: () => Promise<T>,
    message: string | ((result: T) => string) = "Изменения сохранены",
  ) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await action();
      setRevision((r) => r + 1);
      setNotice(typeof message === "function" ? message(result) : message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function decide(action: string) {
    if (!detail) return;
    await act(
      async () => {
        await api(`/cases/${detail.id}/decisions`, "POST", {
          version: modal === "edit" ? editingVersion : detail.proposal.version,
          action,
          reason,
          reason_code: action === "approve" ? undefined : reasonCode,
          steps: action === "edit_and_approve" ? editedSteps : undefined,
        });
        setModal(null);
        setReason("");
        setReasonCode("");
      },
      action === "reject"
        ? "Проект отклонён. Откройте новую версию и исправьте маршрут."
        : "Решение сохранено. Маршрут передан на публикацию.",
    );
  }
  async function simulateBookingFeedback(
    booking: Booking,
    status: "confirmed" | "rejected" | "cancelled" | "cancel_rejected",
  ) {
    if (!detail || !booking.external_ref) return;
    await act(
      () =>
        api(`/demo/bookings/${booking.id}/feedback`, "POST", {
          case_id: detail.id,
          profile_id: booking.profile_id,
          external_ref: booking.external_ref,
          status,
          reason:
            status === "rejected"
              ? "Выбранное время недоступно"
              : status === "cancel_rejected"
                ? "Отмена уже недоступна"
                : "",
        }),
      status === "confirmed"
        ? "Система записи подтвердила слот"
        : status === "rejected"
          ? "Система записи отказала; слот освобождён"
          : status === "cancelled"
            ? "Система записи подтвердила отмену"
            : "Отмена отклонена; запись сохраняется",
    );
  }
  async function carryOverBooking(booking: Booking) {
    if (!detail?.published_route) return;
    await act(async () => {
      await api(
        `/cases/${detail.id}/bookings/${booking.id}/reconcile`,
        "POST",
        {
          action: "carry_over",
          target_route_id: detail.published_route!.id,
          reason: reconcileReasons[booking.id]?.trim() ?? "",
        },
      );
      setReconcileReasons((current) => {
        const next = { ...current };
        delete next[booking.id];
        return next;
      });
    }, "Существующая запись сохранена в текущем маршруте");
  }
  function edit() {
    setLabPreset(false);
    setEditingVersion(detail?.proposal.version ?? 0);
    setEditedSteps(
      (detail?.proposal.steps.length
        ? detail.proposal.steps
        : defaultSteps
      ).slice(0, 1).map(
        ({ key, title, description, action_type, depends_on, unlock_on, prerequisites }) => ({
          key,
          title,
          description,
          action_type,
          depends_on: [...depends_on],
          unlock_on: [...unlock_on],
          prerequisites: structuredClone(prerequisites ?? []),
        }),
      ),
    );
    setReason("");
    setModal("edit");
  }
  function choose(id: string) {
    setSelected(id);
    if (role === "reviewer") setReviewerOpen(true);
    setDetail(null);
    setPatient(null);
    setNotice("");
    setError("");
  }
  const editable =
    detail && ["draft", "manual"].includes(detail.proposal.status);
  const pendingCount = cases.filter((c) =>
    ["draft", "manual"].includes(c.status),
  ).length;
  const pendingCases = cases.filter((c) => ["draft", "manual"].includes(c.status));
  function switchRole(next: "reviewer" | "patient" | "admin") {
    setRole(next);
    setTab(next === "admin" ? "timeline" : next);
    setModal(null);
    setError("");
    setNotice("");
  }

  return (
    <div className="layout">
      <main>
        <header className="topbar">
          <a className="brand" href="/" aria-label="Patient pathway">
            <span className="brand-mark">P</span><span>Patient pathway</span>
          </a>
          <div className="role-switch" role="group" aria-label="Профиль">
            {([ ["reviewer", "Специалист"], ["patient", "Пациент"], ["admin", "Администратор"] ] as const).map(([id, label]) => (
              <button key={id} type="button" className={role === id ? "active" : ""}
                aria-pressed={role === id} onClick={() => switchRole(id)}>{label}</button>
            ))}
          </div>
        </header>
        <section className="page-heading">
          <div>
            <div className="eyebrow">ОТ ЗАКЛЮЧЕНИЯ К СЛЕДУЮЩЕМУ ШАГУ</div>
            <h1>{role === "reviewer" ? "Заявки на валидацию" : role === "patient" ? "Кабинет пациента" : "История и воронка"}</h1>
            <p>{role === "reviewer" ? "Проверьте следующий шаг до показа пациенту." : role === "patient" ? "Здесь доступен утверждённый следующий шаг и запись." : "События маршрута, решения и конверсия."}</p>
          </div>
          {role === "reviewer" && <button
            className="primary"
            disabled={
              !Object.values(profiles).some((item) => item.demo_scenarios)
            }
            onClick={() => setModal("new")}
          >
            ＋ Добавить исследование
          </button>}
        </section>
        {role !== "patient" && <div className="stat-strip">
          <div>
            <span>Исследований</span>
            <strong>{cases.length.toString().padStart(2, "0")}</strong>
          </div>
          <div>
            <span>Ожидают решения</span>
            <strong>
              {pendingCount.toString().padStart(2, "0")}
              <i className="amber-dot" />
            </strong>
          </div>
          <div>
            <span>Записались на следующий шаг</span>
            <strong>
              {metrics?.counts.booking_confirmed ?? 0}
              <small>случаев</small>
            </strong>
          </div>
          <div className="strip-note">
            Каждый шаг связан
            <br />с основанием в заключении <span>↗</span>
          </div>
        </div>}
        {error && (
          <div className="alert error" role="alert">
            {error}
            <button onClick={() => setError("")} aria-label="Закрыть ошибку">
              ×
            </button>
          </div>
        )}
        {notice && (
          <div className="alert success" role="status">
            {notice}
            <button
              onClick={() => setNotice("")}
              aria-label="Закрыть уведомление"
            >
              ×
            </button>
          </div>
        )}
        {role === "admin" && <section className="case-journal" aria-labelledby="case-journal-title">
          <div className="case-journal-heading">
            <div>
              <h2 id="case-journal-title">Журнал исследований</h2>
              <p>Выберите пациента и его исследование, чтобы открыть маршрут.</p>
            </div>
            <span>{cases.length} записей</span>
          </div>
          <div className="case-journal-columns" aria-hidden="true">
            <span>Пациент</span><span>Исследование и клиника</span><span>Дата</span><span>Состояние</span>
          </div>
          <div className="case-journal-list">
            {cases.map((item) => <button
              type="button"
              key={item.id}
              className={`case-journal-row ${selected === item.id ? "selected" : ""}`}
              aria-current={selected === item.id ? "true" : undefined}
              onClick={() => choose(item.id)}
            >
              <strong className="journal-patient">{patientLabel(item.id)}</strong>
              <span className="journal-study"><strong>{modality(item.modality)}</strong><small>{clinic(item.profile_id, profiles)}</small></span>
              <span className="journal-date">{studyDate(item.created_at)}</span>
              <Badge status={item.status} />
            </button>)}
            {!cases.length && <div className="case-journal-empty">Исследований пока нет.</div>}
          </div>
        </section>}
        <div className={`work-area ${role === "reviewer" && !reviewerOpen ? "queue-view" : "single-view"}`}>
          {role === "reviewer" && !reviewerOpen && <section className="case-list">
            <div className="list-heading">
              <h2>Ожидают решения специалиста</h2>
              <span>{pendingCases.length}</span>
            </div>
            <div className="list-caption">Откройте заявку, чтобы проверить основание и маршрут</div>
            {pendingCases.map((c) => (
              <button
                className={`case-card ${selected === c.id ? "selected" : ""}`}
                key={c.id}
                onClick={() => choose(c.id)}
              >
                <div className="case-card-top">
                  <span className="modality-icon">
                    {c.modality === "MAMMOGRAPHY" ? "MMG" : "CT"}
                  </span>
                  <span className="case-number">
                    {patientLabel(c.id)}
                  </span>
                </div>
                <h3>{modality(c.modality)}</h3>
                <p>{clinic(c.profile_id, profiles)}</p>
                <p className="case-conclusion">{displayConclusion(c.conclusion)}</p>
                <div className="case-card-bottom">
                  <Badge status={c.status} />
                  <span>→</span>
                </div>
              </button>
            ))}
            {!pendingCases.length && (
              <div className="empty small">
                Сейчас нет заявок на проверку. Добавьте исследование.
              </div>
            )}
          </section>}
          {(role !== "reviewer" || reviewerOpen) && <section className="detail">
            {role === "reviewer" && <button className="back-to-list" type="button" onClick={() => setReviewerOpen(false)}>← Все заявки на валидацию</button>}
            {role === "admin" && <div className="tabs" role="tablist">
              {([ ["timeline", "История"], ["metrics", "Воронка"] ] as const).map(([id, title]) => (
                <button
                  role="tab"
                  aria-selected={tab === id}
                  className={tab === id ? "active" : ""}
                  key={id}
                  onClick={() => setTab(id)}
                >
                  {title}
                </button>
              ))}
            </div>}
            {tab === "metrics" ? (
              <div className="panel-content">
                <div className="eyebrow">СОБЫТИЯ МАРШРУТА</div>
                <h2>Как проходит маршрут</h2>
                <p className="muted">
                  Независимые накопительные счётчики уникальных случаев.
                </p>
                {metrics &&
                  Object.entries(metrics.counts).map(([key, value]) => (
                    <div className="funnel-row" key={key}>
                      <span>{eventName[key] ?? key}</span>
                      <div>
                        <i
                          style={{
                            width: `${(value / Math.max(1, metrics.counts.result_received)) * 100}%`,
                          }}
                        />
                      </div>
                      <strong>{value}</strong>
                    </div>
                  ))}
                <p className="footnote">
                  Конверсия из показа версии маршрута в подтверждённую запись
                  за {metrics?.conversion_details.attribution_window_days ?? 7} дней:{" "}
                  {metrics?.booking_conversion == null
                    ? "недостаточно данных"
                    : `${Math.round(metrics.booking_conversion * 100)}%`}
                  {metrics &&
                    ` (${metrics.conversion_details.converted_route_versions} из ${metrics.conversion_details.shown_route_versions})`}
                  . Учитывается запрос записи после показа той же версии и его
                  подтверждение в указанное окно. Для{" "}
                  {metrics?.conversion_details.provisional_route_versions ?? 0} показов
                  без записи окно ещё открыто, поэтому показатель может измениться. Uplift
                  нельзя оценить без контрольной группы.
                </p>
                <h3>Выбор пациента после показа</h3>
                <p className="footnote">
                  Явный отказ: {metrics?.patient_choices.route_versions_with_decline ?? 0} версий
                  маршрута; после отказа вернулись к шагу: {metrics?.patient_choices.route_versions_with_resume ?? 0}.
                  Это события за то же окно и ту же когорту показов. Отсутствие записи
                  не считается отказом; сумма по шагам может превышать число версий.
                </p>
                {metrics?.patient_choices.by_step.map((group) => (
                  <div className="report-card" key={`choice-metric-${group.step_key}`}>
                    <strong>Шаг «{group.step_key}»</strong>
                    <p>
                      Отказов: {group.declined_route_steps}; вернулись к этому шагу: {group.resumed_route_steps}.
                    </p>
                    <p className="muted">
                      Причины первого отказа: {Object.entries(group.first_decline_reasons)
                        .map(([code, count]) => `${declineReasonName[code] ?? code} — ${count}`)
                        .join(", ")}.
                    </p>
                  </div>
                ))}
                <p className="footnote">
                  Построение проекта маршрута: p95{" "}
                  {metrics?.routing_latency.p95_ms == null
                    ? "нет данных"
                    : `${metrics.routing_latency.p95_ms.toFixed(1)} мс`}
                  , p99{" "}
                  {metrics?.routing_latency.p99_ms == null
                    ? "нет данных"
                    : `${metrics.routing_latency.p99_ms.toFixed(1)} мс`}
                  {metrics && ` (${metrics.routing_latency.count} заключений)`}.
                  Измерение начинается с разбора полей и заканчивается до коммита
                  проекта. Передача заключения, работа ИИ, решение специалиста и
                  публикация в него не входят.
                </p>
                <p className="footnote">
                  Проект → решение специалиста: p95{" "}
                  {metrics?.workflow_latency.proposal_to_decision.p95_ms == null
                    ? "нет данных"
                    : `${metrics.workflow_latency.proposal_to_decision.p95_ms.toFixed(1)} мс`}
                  , p99{" "}
                  {metrics?.workflow_latency.proposal_to_decision.p99_ms == null
                    ? "нет данных"
                    : `${metrics.workflow_latency.proposal_to_decision.p99_ms.toFixed(1)} мс`}
                  {metrics &&
                    ` (${metrics.workflow_latency.proposal_to_decision.count} решений)`}
                  . Утверждение → публикация: p95{" "}
                  {metrics?.workflow_latency.approval_to_publication.p95_ms == null
                    ? "нет данных"
                    : `${metrics.workflow_latency.approval_to_publication.p95_ms.toFixed(1)} мс`}
                  {metrics &&
                    ` (${metrics.workflow_latency.approval_to_publication.count} публикаций)`}
                  . Это интервалы между сохранёнными событиями; они не включают
                  работу ИИ до получения заключения и не подтверждают время всего
                  приёма.
                </p>
                <div className="quality-section">
                  <div className="eyebrow">ОБРАТНАЯ СВЯЗЬ СПЕЦИАЛИСТА</div>
                  <h3>Где специалист меняет проект модели</h3>
                  <p className="muted">
                    Счётчики по версиям модели и типам правок. Здесь нет
                    идентификаторов пациентов, текста заключений и комментариев
                    специалиста. Правки поступают на разметку и оценку перед
                    выпуском следующей версии модели.
                  </p>
                  <p className="footnote">
                    Решений: {qualityReview?.total_decisions ?? 0}
                  </p>
                  {qualityReview?.groups.length ? (
                    <div className="quality-grid">
                      {qualityReview.groups.map((group) => (
                        <div
                          className="quality-card"
                          key={`${group.profile_id}:${group.modality}:${group.exam_purpose}:${group.ruleset_version}:${group.rule_id}:${group.proposal_mode}`}
                        >
                          <strong>
                            {group.rule_id === "NO_UNIQUE_RULE"
                              ? "Ручной выбор"
                              : group.rule_id}
                          </strong>
                          <small>
                            {clinic(group.profile_id, profiles)} ·{" "}
                            {modality(group.modality)} ·{" "}
                            {examPurposeName[group.exam_purpose]} ·{" "}
                            {group.proposal_mode === "manual"
                              ? "ручное решение"
                              : "проект модели"}
                          </small>
                          <p>
                            Решений: {group.decisions} · без правки:{" "}
                            {group.approved}
                            {" · "}правок: {group.edited} · отклонений:{" "}
                            {group.rejected}
                          </p>
                          {Object.entries(group.edit_types).map(
                            ([kind, count]) => (
                              <p key={kind}>
                                {editTypeName[kind] ?? kind}: {count}
                              </p>
                            ),
                          )}
                          {Object.entries(group.reason_codes).map(
                            ([code, count]) => (
                              <p key={code}>
                                {reasonCodeName[code] ?? code}: {count}
                              </p>
                            ),
                          )}
                          <small>Версия модели: {group.ruleset_version}</small>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">
                      После решения специалиста появится сводка для обновления
                      модели.
                    </p>
                  )}
                </div>
              </div>
            ) : !detail ? (
              <div className="empty">
                <div className="empty-symbol">◇</div>
                <h2>
                  {cases.length
                    ? "Загружаем исследование"
                    : "Начните с исследования"}
                </h2>
                <p>
                  Выберите случай, чтобы увидеть основания и дальнейший путь.
                </p>
              </div>
            ) : tab === "reviewer" ? (
              <div className="panel-content">
                <div className="detail-title">
                  <div>
                    <div className="eyebrow">
                      ТЕКУЩИЙ ПРИЁМ ·{" "}
                      {detail.source_kind.includes("dicom")
                        ? "DICOM SR"
                        : "BFT JSON"}
                    </div>
                    <h2>{modality(detail.modality)}</h2>
                    <span className="study-patient">{patientLabel(detail.id)}</span>
                  </div>
                  <Badge status={detail.proposal.status} />
                </div>
                <div className="report-card">
                  <div className="section-label">
                    <span>Заключение ИИ</span>
                    <span>Версия {detail.report.source_version}</span>
                  </div>
                  <p>{displayConclusion(detail.report.conclusion)}</p>
                  <div className="facts">
                    {detail.report.facts.map((f) => (
                      <div
                        className="fact"
                        key={f.code}
                        title={f.source_pointer}
                      >
                        <span>
                          {f.code === "mmg_rads_right"
                            ? "BI-RADS · справа"
                            : f.code === "mmg_rads_left"
                              ? "BI-RADS · слева"
                              : "Количество узлов"}
                        </span>
                        <strong>
                          {String(f.value)} {f.unit ?? ""}
                        </strong>
                      </div>
                    ))}
                  </div>
                </div>
                {detail.proposal.warnings?.map((w) => (
                  <div className="warning" key={w}>
                    <span>!</span>
                    {w}
                  </div>
                ))}
                <div className="section-title">
                  <h3>Предлагаемый следующий шаг</h3>
                  <span>Версия {detail.proposal.version}</span>
                </div>
                <div className="route-steps">
                  {detail.proposal.steps.map((s, i) => (
                    <article className="route-step" key={s.key}>
                      <div className="step-marker">{i + 1}</div>
                      <div>
                        <h4>{s.title}</h4>
                        <p>{s.description}</p>
                        {s.prerequisites?.map((item) => (
                          <p className="dependency" key={item.key}>
                            Анализ параллельно: {item.title} ·{" "}
                            {item.gate === "before_booking"
                              ? "результат нужен до записи"
                              : "результат нужен до выполнения шага"}
                          </p>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
                {!detail.proposal.steps.length && (
                  <div className="empty-route">
                    {detail.proposal.status === "manual"
                      ? "Автоматический путь не выбран. Специалист может задать его вручную."
                      : "Модель не предлагает нового шага. Решение подтверждает специалист."}
                  </div>
                )}
                <div className="review-note">
                  <span>◇</span>
                  <p>
                    Проверьте следующий шаг, подготовку и основания перед подтверждением.
                  </p>
                </div>
                {editable && (
                  <div className="action-row">
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={edit}
                    >
                      Изменить маршрут
                    </button>
                    <button
                      className="primary"
                      disabled={busy || detail.proposal.status === "manual"}
                      onClick={() => decide("approve")}
                    >
                      Подтвердить маршрут <span>→</span>
                    </button>
                  </div>
                )}
                {detail.proposal.status === "approved" && (
                  <p className="muted">
                    Публикация выполняется фоновым процессом…
                  </p>
                )}
                <details className="evidence">
                  <summary>
                    Основания решения{" "}
                    <span>
                      {detail.proposal.trace?.filter((t) => t.matched).length ??
                        0}{" "}
                      факторов
                    </span>
                  </summary>
                  {detail.proposal.trace
                    ?.filter((t) => t.matched)
                    .map((t) => (
                      <div key={t.rule_id}>
                        <b>{t.rule_id}</b>
                        {t.checks.map((c, i) => (
                          <p key={i}>
                            <code>{c.field}</code> = {String(c.actual)}{" "}
                            <span className="muted">· {c.source_pointer}</span>
                          </p>
                        ))}
                      </div>
                    ))}
                  <small>{detail.proposal.ruleset_version}</small>
                  {!detail.proposal.trace?.some((t) => t.matched) && (
                    <p>Модель передала выбор специалисту. Причины показаны выше.</p>
                  )}
                </details>
                {detail.published_route?.steps
                  .filter((s) => s.choice?.status === "declined")
                  .map((s) => (
                    <div className="warning" key={`choice-${s.key}`}>
                      Пациент отказался от шага «{s.title}»: {declineReasonName[s.choice!.reason_code ?? ""] ?? "другая причина"}.
                      Маршрут остаётся доступным, если пациент изменит решение.
                    </div>
                  ))}
                {detail.published_route?.steps
                  .filter((s) => s.booking?.status === "awaiting_confirmation")
                  .map((s) => (
                    <div className="simulator" key={`feedback-${s.key}`}>
                      <h4>Ответ системы записи</h4>
                      <p>
                        {s.title} · {time(s.booking!.slot)}
                      </p>
                      <div className="inline-fields">
                        <button
                          className="secondary"
                          disabled={busy}
                          onClick={() =>
                            simulateBookingFeedback(s.booking!, "confirmed")
                          }
                        >
                          Подтвердить слот
                        </button>
                        <button
                          className="secondary"
                          disabled={busy}
                          onClick={() =>
                            simulateBookingFeedback(s.booking!, "rejected")
                          }
                        >
                          Отказать в записи
                        </button>
                      </div>
                    </div>
                  ))}
                {detail.previous_bookings
                  .filter((b) => b.status === "awaiting_confirmation")
                  .map((b) => (
                    <div
                      className="simulator"
                      key={`previous-feedback-${b.id}`}
                    >
                      <h4>
                        Прежний маршрут v{b.route_version} · ответ системы
                        записи
                      </h4>
                      <p>
                        {b.title} · {time(b.slot)}. Сначала согласуйте этот
                        запрос.
                      </p>
                      <div className="inline-fields">
                        <button
                          className="secondary"
                          disabled={busy}
                          onClick={() =>
                            simulateBookingFeedback(b, "confirmed")
                          }
                        >
                          Подтвердить прежний слот
                        </button>
                        <button
                          className="secondary"
                          disabled={busy}
                          onClick={() => simulateBookingFeedback(b, "rejected")}
                        >
                          Отказать в прежней записи
                        </button>
                      </div>
                    </div>
                  ))}
                {[
                  ...(detail.published_route?.steps
                    .filter((s) => s.booking?.status === "cancel_requested")
                    .map((s) => ({ booking: s.booking!, title: s.title })) ?? []),
                  ...detail.previous_bookings
                    .filter((b) => b.status === "cancel_requested")
                    .map((b) => ({ booking: b, title: b.title })),
                ].map(({ booking, title }) => (
                  <div className="simulator" key={`cancel-feedback-${booking.id}`}>
                    <h4>Ответ системы записи по отмене</h4>
                    <p>{title} · {time(booking.slot)}</p>
                    <div className="inline-fields">
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() => simulateBookingFeedback(booking, "cancelled")}
                      >
                        Подтвердить отмену
                      </button>
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() => simulateBookingFeedback(booking, "cancel_rejected")}
                      >
                        Отказать в отмене
                      </button>
                    </div>
                  </div>
                ))}
                {detail.previous_bookings.map((b) => {
                  const targetStep = detail.published_route?.steps.find(
                    (step) =>
                      step.key === b.step_key &&
                      step.availability === "available",
                  );
                  if (
                    detail.pending_review ||
                    b.status === "cancel_requested" ||
                    !targetStep
                  ) return null;
                  return (
                    <div className="simulator" key={`reconcile-${b.id}`}>
                      <h4>Согласовать прежнюю запись</h4>
                      <p>
                        {b.title} · {time(b.slot)} · маршрут v{b.route_version}.
                        Убедитесь, что прежняя услуга подходит для нового шага.
                      </p>
                      <div className="inline-fields">
                        <input
                          aria-label={`Причина сохранения записи ${b.title}`}
                          placeholder="Причина сохранения записи"
                          value={reconcileReasons[b.id] ?? ""}
                          onChange={(event) =>
                            setReconcileReasons({
                              ...reconcileReasons,
                              [b.id]: event.target.value,
                            })
                          }
                        />
                        <button
                          className="secondary"
                          disabled={busy || !reconcileReasons[b.id]?.trim()}
                          onClick={() => carryOverBooking(b)}
                        >
                          Сохранить в новом маршруте
                        </button>
                      </div>
                    </div>
                  );
                })}
                {detail.published_route?.steps.flatMap((s) =>
                  (s.prerequisites ?? []).filter((item) => item.booking?.status === "confirmed"),
                ).map((item) => (
                  <div className="simulator" key={`lab-result-${item.key}`}>
                    <h4>Результат подготовительного анализа</h4>
                    <p>{item.title}</p>
                    <div className="action-row">
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() => act(
                          () => api(`/cases/${detail.id}/prerequisite-results`, "POST", {
                            route_id: detail.published_route!.id,
                            booking_id: item.booking!.id,
                            requirement_key: item.key,
                            outcome: "accepted",
                          }),
                          "Подготовительный результат принят",
                        )}
                      >
                        Результат готов и принят
                      </button>
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() => act(
                          () => api(`/cases/${detail.id}/prerequisite-results`, "POST", {
                            route_id: detail.published_route!.id,
                            booking_id: item.booking!.id,
                            requirement_key: item.key,
                            outcome: "rejected",
                          }),
                          "Нужна повторная подготовка",
                        )}
                      >
                        Результат не подходит
                      </button>
                    </div>
                  </div>
                ))}
                {detail.published_route?.steps
                  .filter((s) => s.booking?.status === "confirmed")
                  .map((s) => (
                    <div className="simulator" key={s.key}>
                      <h4>Результат шага</h4>
                      <p>{s.title}</p>
                      {s.prerequisites?.some((item) => item.readiness !== "ready") && (
                        <p className="warning">До завершения шага нужны принятые результаты подготовки.</p>
                      )}
                      <div className="inline-fields">
                        <select
                          aria-label="Результат шага"
                          value={outcomes[s.key] ?? "followup_needed"}
                          onChange={(e) =>
                            setOutcomes({
                              ...outcomes,
                              [s.key]: e.target.value,
                            })
                          }
                        >
                          <option value="followup_needed">
                            Требуется следующий шаг
                          </option>
                          <option value="resolved">
                            Продолжение не требуется
                          </option>
                          <option value="replan">
                            Нужно пересмотреть маршрут
                          </option>
                        </select>
                        <button
                          className="secondary"
                          disabled={busy || s.prerequisites?.some((item) => item.readiness !== "ready")}
                          onClick={() =>
                            act(
                              () =>
                                api(`/cases/${detail.id}/results`, "POST", {
                                  route_id: detail.published_route!.id,
                                  step_key: s.key,
                                  outcome: outcomes[s.key] ?? "followup_needed",
                                  note: "Результат шага получен",
                                }),
                              "Результат шага зарегистрирован",
                            )
                          }
                        >
                          Загрузить результат
                        </button>
                      </div>
                    </div>
                  ))}
                <button
                  className="text-button revision-button"
                  disabled={busy}
                  onClick={() =>
                    act(
                      () =>
                        api(`/cases/${detail.id}/demo-revision`, "POST", {
                          profile_id: detail.profile_id,
                          modality: detail.modality,
                          scenario: "normal",
                          exam_purpose: detail.report.exam_purpose,
                        }),
                      "Получена новая версия заключения",
                    )
                  }
                >
                  Получить исправленное заключение
                </button>
              </div>
            ) : tab === "patient" ? (
              <div className="panel-content patient-panel">
                <div className="patient-brand">
                  {clinic(detail.profile_id, profiles)}
                  <span>Личный кабинет</span>
                </div>
                <div className="eyebrow">ПОСЛЕ ИССЛЕДОВАНИЯ</div>
                <h2>Ваш следующий шаг</h2>
                <span className="study-patient">{patientLabel(detail.id)} · {modality(detail.modality)}</span>
                <p className="muted">
                  Здесь появляются рекомендации, которые подтвердил специалист.
                </p>
                {!patient?.route ? (
                  <div className="patient-wait">
                    <span>◷</span>
                    <h3>Специалист рассматривает результат</h3>
                    <p>Маршрут появится после подтверждения.</p>
                  </div>
                ) : (
                  <>
                    <div className="approved-note">
                      ✓ Подтверждено специалистом · версия{" "}
                      {patient.route.version}
                    </div>
                    {!patient.route.steps.length && (
                      <div className="patient-no-step">
                        <strong>По текущему заключению новый шаг не назначен</strong>
                        <p>Это решение подтвердил специалист. Если появится новый результат, маршрут будет рассмотрен снова.</p>
                      </div>
                    )}
                    {patient.pending_review && (
                      <div className="warning">
                        Получены новые данные. Запись временно приостановлена до
                        решения специалиста.
                      </div>
                    )}
                    {patient.route.steps
                      .filter((s) => s.availability !== "not_needed")
                      .map((s) => (
                        <article className="patient-step" key={s.key}>
                          <h3>{s.title}</h3>
                          <p>{s.description}</p>
                          {!!s.prerequisites?.length && (
                            <div className="preparation-list">
                              <strong>Подготовка к этому шагу</strong>
                              {s.prerequisites.map((item) => (
                                <div className="preparation-card" key={item.key}>
                                  <h4>{item.title}</h4>
                                  <p>{item.description}</p>
                                  <small>
                                    {item.gate === "before_booking"
                                      ? "Результат нужен до записи на основной шаг"
                                      : "Можно записаться параллельно; результат нужен до выполнения основного шага"}
                                  </small>
                                  {item.readiness === "ready" ? (
                                    <p className="confirmed">✓ Результат принят специалистом</p>
                                  ) : item.booking?.status === "confirmed" ? (
                                    <div className="confirmed">
                                      <p>Анализ запланирован: {time(item.booking.slot)}</p>
                                      <button
                                        className="text-button"
                                        disabled={busy || patient.pending_review}
                                        onClick={() => act(
                                          () => api<Booking>(
                                            `/patient/cases/${detail.id}/bookings/${item.booking!.id}/cancel`,
                                            "POST", undefined, detail.patient_token,
                                          ),
                                          "Запись на анализ отменена",
                                        )}
                                      >Отменить запись на анализ</button>
                                    </div>
                                  ) : item.booking?.status === "awaiting_confirmation" ||
                                    item.booking?.status === "requested" ? (
                                    <p>Ожидаем подтверждения записи на анализ.</p>
                                  ) : item.booking?.status === "cancel_requested" ? (
                                    <p>Ожидаем подтверждения отмены анализа.</p>
                                  ) : (
                                    <>
                                      {item.readiness === "rejected" && (
                                        <p className="warning">Результат не принят. Нужна повторная подготовка.</p>
                                      )}
                                      {item.readiness === "expired" && (
                                        <p className="warning">Срок действия результата истёк.</p>
                                      )}
                                      <div className="slot-grid">
                                        {["tomorrow-09:00", "tomorrow-11:30", "tomorrow-15:00"].map((slot) => (
                                          <button
                                            className={(slots[item.key] ?? "tomorrow-09:00") === slot ? "chosen" : ""}
                                            key={slot}
                                            onClick={() => setSlots({ ...slots, [item.key]: slot })}
                                          >{time(slot)}</button>
                                        ))}
                                      </div>
                                      <button
                                        className="secondary"
                                        disabled={busy || patient.pending_review}
                                        onClick={() => act(
                                          () => api<Booking>(`/patient/cases/${detail.id}/bookings`, "POST", {
                                            route_id: patient.route!.id,
                                            step_key: item.key,
                                            slot: slots[item.key] ?? "tomorrow-09:00",
                                          }, detail.patient_token),
                                          "Запрос на анализ отправлен",
                                        )}
                                      >Записаться на анализ</button>
                                    </>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                          {s.booking_gate_open === false && s.availability !== "completed" && (
                            <p className="warning">Запись на основной шаг откроется после результата подготовки.</p>
                          )}
                          {s.availability === "completed" ? (
                            <Badge status="completed" />
                          ) : s.booking?.status === "confirmed" ? (
                            <div className="confirmed">
                              <strong>✓ Вы записаны</strong>
                              <p>{time(s.booking.slot)}</p>
                              <small>
                                Номер записи {bookingReference(s.booking.external_ref)}
                              </small>
                              {s.booking.status_reason && (
                                <p className="warning">{s.booking.status_reason}</p>
                              )}
                              <button
                                className="text-button"
                                disabled={busy}
                                onClick={() =>
                                  act(
                                    () =>
                                      api<Booking>(
                                        `/patient/cases/${detail.id}/bookings/${s.booking!.id}/cancel`,
                                        "POST",
                                        undefined,
                                        detail.patient_token,
                                      ),
                                    (booking) =>
                                      booking.status === "cancel_requested"
                                        ? "Запрос отмены отправлен. Дождитесь ответа системы записи."
                                        : "Запись отменена. Можно выбрать другое время.",
                                  )
                                }
                              >
                                Отменить запись
                              </button>
                            </div>
                          ) : s.booking?.status === "cancel_requested" ? (
                            <div className="confirmed">
                              <strong>Отмена ожидает подтверждения</strong>
                              <p>{time(s.booking.slot)} · запись пока действует</p>
                            </div>
                          ) : s.booking?.status === "requested" ||
                            s.booking?.status === "awaiting_confirmation" ? (
                            <div className="confirmed">
                              <strong>Запрос на запись отправлен</strong>
                              <p>
                                {time(s.booking.slot)} · ожидаем подтверждения
                                времени
                              </p>
                              <small>
                                Номер запроса {bookingReference(s.booking.external_ref)}
                              </small>
                            </div>
                          ) : s.choice?.status === "declined" ? (
                            <div className="confirmed">
                              <strong>Вы отказались от этого шага</strong>
                              <p>Причина: {declineReasonName[s.choice.reason_code ?? ""] ?? "другая причина"}</p>
                              <button
                                className="secondary"
                                disabled={busy || patient.pending_review}
                                onClick={() =>
                                  act(
                                    () =>
                                      api(
                                        `/patient/cases/${detail.id}/steps/${s.key}/resume`,
                                        "POST",
                                        { route_id: patient.route!.id },
                                        detail.patient_token,
                                      ),
                                    "Шаг снова доступен для записи",
                                  )
                                }
                              >
                                Вернуться к записи
                              </button>
                            </div>
                          ) : (
                            <>
                              {s.booking?.status === "no_slots" && (
                                <div className="warning">
                                  Координатор поможет подобрать время. Запрос
                                  сохранён.
                                </div>
                              )}
                              {s.booking?.status === "rejected" && (
                                <div className="warning">
                                  Запись не подтверждена.{" "}
                                  {s.booking.status_reason} Выберите другое
                                  время.
                                </div>
                              )}
                              <label className="field-label">
                                Удобное время
                              </label>
                              <div className="slot-grid">
                                {[
                                  "tomorrow-09:00",
                                  "tomorrow-11:30",
                                  "tomorrow-15:00",
                                ].map((slot) => (
                                  <button
                                    className={
                                      (slots[s.key] ?? (s.prerequisites?.length ? "tomorrow-15:00" : "tomorrow-09:00")) ===
                                      slot
                                        ? "chosen"
                                        : ""
                                    }
                                    key={slot}
                                    onClick={() =>
                                      setSlots({ ...slots, [s.key]: slot })
                                    }
                                  >
                                    {time(slot)}
                                  </button>
                                ))}
                              </div>
                              <button
                                className="primary full"
                                disabled={busy || patient.pending_review || s.booking_gate_open === false}
                                onClick={() =>
                                  act(
                                    () =>
                                      api<Booking>(
                                        `/patient/cases/${detail.id}/bookings`,
                                        "POST",
                                        {
                                          route_id: patient.route!.id,
                                          step_key: s.key,
                                          slot:
                                            slots[s.key] ?? (s.prerequisites?.length ? "tomorrow-15:00" : "tomorrow-09:00"),
                                        },
                                        detail.patient_token,
                                      ),
                                    (booking) =>
                                      booking.status === "confirmed"
                                        ? "Запись подтверждена"
                                        : "Запрос передан. Ожидаем подтверждения времени.",
                                  )
                                }
                              >
                                Записаться
                              </button>
                              <button
                                className="text-button"
                                disabled={busy || patient.pending_review || s.booking_gate_open === false}
                                onClick={() =>
                                  act(
                                    () =>
                                      api(
                                        `/patient/cases/${detail.id}/bookings`,
                                        "POST",
                                        {
                                          route_id: patient.route!.id,
                                          step_key: s.key,
                                          slot: "no-slots",
                                        },
                                        detail.patient_token,
                                      ),
                                    "Создан запрос координатору",
                                  )
                                }
                              >
                                Нужна помощь с выбором времени
                              </button>
                              <label className="field-label" htmlFor={`decline-${s.key}`}>
                                Если не планируете этот шаг, укажите причину
                              </label>
                              <select
                                id={`decline-${s.key}`}
                                value={declineReasons[s.key] ?? ""}
                                onChange={(event) =>
                                  setDeclineReasons({
                                    ...declineReasons,
                                    [s.key]: event.target.value,
                                  })
                                }
                              >
                                <option value="">Выберите причину</option>
                                {Object.entries(declineReasonName).map(([code, label]) => (
                                  <option key={code} value={code}>{label}</option>
                                ))}
                              </select>
                              <button
                                className="text-button"
                                disabled={busy || patient.pending_review || !declineReasons[s.key]}
                                onClick={() =>
                                  act(
                                    () =>
                                      api(
                                        `/patient/cases/${detail.id}/steps/${s.key}/decline`,
                                        "POST",
                                        {
                                          route_id: patient.route!.id,
                                          reason_code: declineReasons[s.key],
                                        },
                                        detail.patient_token,
                                      ),
                                    "Ваш выбор сохранён",
                                  )
                                }
                              >
                                Отказаться от шага
                              </button>
                            </>
                          )}
                        </article>
                      ))}
                    {!patient.route.steps.length && (
                      <div className="patient-wait">
                        <span>✓</span>
                        <h3>Дополнительные шаги не назначены</h3>
                        <p>
                          Решение подтверждено специалистом по этому
                          исследованию.
                        </p>
                      </div>
                    )}
                  </>
                )}
                {!!patient?.previous_bookings?.length && (
                  <section className="patient-step">
                    <h3>Ранее оформленные записи</h3>
                    <p>
                      Маршрут обновлён. Эти записи сохранены: согласуйте их с
                      клиникой перед новой записью.
                    </p>
                    {patient.previous_bookings.map((b) => (
                      <div className="confirmed" key={b.id}>
                        <strong>{b.title}</strong>
                        <p>
                          {time(b.slot)} · маршрут v{b.route_version} ·{" "}
                          {b.status === "confirmed"
                            ? "подтверждена"
                            : b.status === "cancel_requested"
                              ? "отмена ожидает подтверждения"
                              : "ожидает подтверждения"}
                        </p>
                        {b.status === "confirmed" && (
                          <button
                            className="text-button"
                            disabled={busy}
                            onClick={() =>
                              act(
                                () =>
                                  api<Booking>(
                                    `/patient/cases/${detail.id}/bookings/${b.id}/cancel`,
                                    "POST",
                                    undefined,
                                    detail.patient_token,
                                  ),
                                (booking) =>
                                  booking.status === "cancel_requested"
                                    ? "Запрос отмены прежней записи отправлен"
                                    : "Прежняя запись отменена",
                              )
                            }
                          >
                            Отменить прежнюю запись
                          </button>
                        )}
                      </div>
                    ))}
                  </section>
                )}
              </div>
            ) : (
              <div className="panel-content">
                <div className="eyebrow">ПРОЗРАЧНОСТЬ РЕШЕНИЙ</div>
                <h2>История маршрута</h2>
                <span className="study-patient">{patientLabel(detail.id)} · {modality(detail.modality)}</span>
                <div className="version-chips">
                  {detail.history.map((h) => (
                    <span key={h.id}>
                      v{h.version} · {statusName[h.status]} ·{" "}
                      {profiles[h.profile_id]?.input === "dicom" ? "DICOM SR" : "JSON"}
                      {" · "}{h.profile_id}
                    </span>
                  ))}
                </div>
                {detail.decisions
                  .filter((d) => d.reason)
                  .map((d, i) => (
                    <div className="report-card" key={i}>
                      <strong>Причина решения специалиста</strong>
                      <p>{d.reason}</p>
                    </div>
                  ))}
                <div className="timeline">
                  {detail.events.map((e) => (
                    <div key={e.id}>
                      <i />
                      <section>
                        <strong>{eventName[e.kind] ?? e.kind}</strong>
                        <small>
                          {new Date(e.created_at).toLocaleTimeString("ru-RU")}
                        </small>
                      </section>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>}
        </div>
        <footer className="page-footer">
          <span>Patient pathway · следующий шаг после заключения</span>
        </footer>
      </main>
      {modal && (
        <div className="modal-backdrop" onClick={() => !busy && setModal(null)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-label={
              modal === "new" ? "Новое исследование" : "Изменение маршрута"
            }
            className="modal"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="close-modal"
              aria-label="Закрыть"
              onClick={() => setModal(null)}
            >
              ×
            </button>
            {modal === "new" ? (
              <>
                <div className="eyebrow">ДАННЫЕ ИССЛЕДОВАНИЯ</div>
                <h2>Новое исследование</h2>
                <p className="muted">
                  Выберите источник, исследование и клиническую ситуацию.
                </p>
                <label>
                  Профиль подключения
                  <select
                    value={profile}
                    onChange={(e) => {
                      setProfile(e.target.value);
                      const supported = Object.keys(
                        profiles[e.target.value]?.fields ?? {},
                      );
                      if (!supported.includes(newModality))
                        setNewModality(supported[0] ?? "");
                    }}
                  >
                    {Object.entries(profiles)
                      .filter(([, value]) => value.demo_scenarios)
                      .map(([id, value]) => (
                        <option key={id} value={id}>
                          {value.label} ·{" "}
                          {value.input === "dicom" ? "DICOM SR" : "JSON"}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Исследование
                  <select
                    aria-label="Исследование"
                    value={newModality}
                    onChange={(e) => {
                      setNewModality(e.target.value);
                      if (!scenarioOptions[e.target.value]?.some((item) => item.value === scenario))
                        setScenario("finding");
                    }}
                  >
                    {Object.keys(profiles[profile]?.fields ?? {}).map((id) => (
                      <option key={id} value={id}>
                        {modality(id)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Ситуация
                  <select
                    value={scenario}
                    onChange={(e) => setScenario(e.target.value)}
                  >
                    {(scenarioOptions[newModality] ?? [])
                      .filter((item) => item.value !== "multiple_with_lab" ||
                        Object.keys(profiles[profile]?.services ?? {}).some((key) => key.startsWith("lab_")))
                      .map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                  </select>
                </label>
                {scenario === "multiple_with_lab" && <p className="demo-scenario-note">
                  Модель предложит консультацию. Затем откроется редактор: анализ добавляет и утверждает специалист, его необходимость не выводится из числа узлов.
                </p>}
                <label>
                  Назначение исследования
                  <select
                    value={purpose}
                    onChange={(e) => setPurpose(e.target.value)}
                  >
                    <option value="diagnostic">Диагностика</option>
                    <option value="screening">Скрининг</option>
                    <option value="unknown">Неизвестно</option>
                  </select>
                </label>
                <button
                  className="primary full"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      const result = await api<{ case_id: string }>(
                        "/demo/cases",
                        "POST",
                        {
                          profile_id: profile,
                          modality: newModality,
                          scenario: scenario === "multiple_with_lab" ? "multiple" : scenario,
                          exam_purpose: purpose,
                        },
                      );
                      choose(result.case_id);
                      setTab("reviewer");
                      setReviewerOpen(true);
                      setModal(null);
                      if (scenario === "multiple_with_lab") {
                        const loaded = await api<CaseDetail>(`/cases/${result.case_id}`);
                        const serviceKey = Object.keys(profiles[profile]?.services ?? {})
                          .find((key) => key.startsWith("lab_"));
                        if (loaded.proposal.steps.length && serviceKey) {
                          const modelStep = loaded.proposal.steps[0];
                          setDetail(loaded);
                          setEditingVersion(loaded.proposal.version);
                          setEditedSteps([{ key: modelStep.key,
                            title: modelStep.title,
                            description: modelStep.description,
                            action_type: modelStep.action_type,
                            depends_on: [...modelStep.depends_on],
                            unlock_on: [...modelStep.unlock_on],
                            prerequisites: [{
                            key: "lab_1",
                            title: "Анализ по решению специалиста",
                            description: "Результат нужен до выполнения консультации.",
                            kind: "lab",
                            service_key: serviceKey,
                            gate: "before_execution",
                          }] }]);
                          setReasonCode("route_logic");
                          setReason("Специалист добавил подготовку перед консультацией.");
                          setLabPreset(true);
                          setModal("edit");
                        }
                      }
                    }, "Исследование поступило")
                  }
                >
                  Создать исследование
                </button>
              </>
            ) : (
              <>
                <div className="eyebrow">РЕШЕНИЕ СПЕЦИАЛИСТА</div>
                <h2>Скорректировать путь</h2>
                {labPreset && <p className="demo-scenario-note">Анализ добавляет специалист. Модель его не выбирала.</p>}
                {editedSteps.map((s, i) => (
                  <div className="edit-step" key={s.key}>
                    <label>
                      Следующий шаг
                      <input
                        value={s.title}
                        onChange={(e) =>
                          setEditedSteps(
                            editedSteps.map((v, j) =>
                              i === j ? { ...v, title: e.target.value } : v,
                            ),
                          )
                        }
                      />
                    </label>
                    <label>
                      Тип услуги
                      <select
                        value={s.action_type}
                        onChange={(e) => setEditedSteps(editedSteps.map((v, j) =>
                          i === j ? { ...v, action_type: e.target.value as Step["action_type"] } : v,
                        ))}
                      >
                        <option value="consultation">Консультация</option>
                        <option value="diagnostic_imaging">Диагностическое исследование</option>
                        <option value="procedure">Процедура</option>
                        <option value="followup">Повторный приём</option>
                      </select>
                    </label>
                    <label>
                      Пояснение пациенту
                      <textarea
                        value={s.description}
                        onChange={(e) =>
                          setEditedSteps(
                            editedSteps.map((v, j) =>
                              i === j
                                ? { ...v, description: e.target.value }
                                : v,
                            ),
                          )
                        }
                      />
                    </label>
                    <div className="preparation-list">
                      <strong>Анализы для подготовки к этому шагу</strong>
                      {(s.prerequisites ?? []).map((item, index) => (
                        <div className="preparation-card" key={item.key}>
                          <label>
                            Название анализа
                            <input
                              value={item.title}
                              onChange={(e) => setEditedSteps(editedSteps.map((v, j) =>
                                i === j ? { ...v, prerequisites: (v.prerequisites ?? []).map((p, k) =>
                                  index === k ? { ...p, title: e.target.value } : p,
                                ) } : v,
                              ))}
                            />
                          </label>
                          <label>
                            Пояснение
                            <input
                              value={item.description}
                              onChange={(e) => setEditedSteps(editedSteps.map((v, j) =>
                                i === j ? { ...v, prerequisites: (v.prerequisites ?? []).map((p, k) =>
                                  index === k ? { ...p, description: e.target.value } : p,
                                ) } : v,
                              ))}
                            />
                          </label>
                          <label>
                            Условие готовности
                            <select
                              value={item.gate}
                              onChange={(e) => setEditedSteps(editedSteps.map((v, j) =>
                                i === j ? { ...v, prerequisites: (v.prerequisites ?? []).map((p, k) =>
                                  index === k ? { ...p, gate: e.target.value as typeof p.gate } : p,
                                ) } : v,
                              ))}
                            >
                              <option value="before_execution">До выполнения основного шага</option>
                              <option value="before_booking">До записи на основной шаг</option>
                            </select>
                          </label>
                          <label>
                            Услуга из профиля клиники
                            <select
                              value={item.service_key}
                              onChange={(e) => setEditedSteps(editedSteps.map((v, j) =>
                                i === j ? { ...v, prerequisites: (v.prerequisites ?? []).map((p, k) =>
                                  index === k ? { ...p, service_key: e.target.value } : p,
                                ) } : v,
                              ))}
                            >
                              {Object.keys(profiles[detail?.source_profile_id ?? ""]?.services ?? {})
                                .filter((key) => key.startsWith("lab_"))
                                .map((key) => <option key={key} value={key}>{key}</option>)}
                            </select>
                          </label>
                          <button className="text-button" onClick={() => setEditedSteps(editedSteps.map((v, j) =>
                            i === j ? { ...v, prerequisites: (v.prerequisites ?? []).filter((p) => p.key !== item.key) } : v,
                          ))}>Убрать анализ</button>
                        </div>
                      ))}
                      {(s.prerequisites?.length ?? 0) < 3 &&
                        Object.keys(profiles[detail?.source_profile_id ?? ""]?.services ?? {}).some((key) => key.startsWith("lab_")) && (
                        <button
                          className="text-button"
                          onClick={() => {
                            const current = s.prerequisites ?? [];
                            const number = [1, 2, 3].find((n) => !current.some((p) => p.key === `lab_${n}`));
                            const serviceKey = Object.keys(profiles[detail?.source_profile_id ?? ""]?.services ?? {})
                              .find((key) => key.startsWith("lab_"))!;
                            setEditedSteps(editedSteps.map((v, j) => i === j ? {
                              ...v,
                              prerequisites: [...current, {
                                key: `lab_${number}`,
                                title: "Анализ по решению специалиста",
                                description: "Сдать и получить принятый результат до выполнения следующего шага.",
                                kind: "lab",
                                service_key: serviceKey,
                                gate: "before_execution",
                              }],
                            } : v));
                          }}
                        >Добавить анализ</button>
                      )}
                    </div>
                  </div>
                ))}
                <div className="edit-tools">
                  <button
                    className="text-button"
                    onClick={() =>
                      setEditedSteps([structuredClone(defaultSteps[0])])
                    }
                  >
                    Один следующий шаг
                  </button>
                  <button
                    className="text-button"
                    onClick={() => setEditedSteps([])}
                  >
                    Без новых шагов
                  </button>
                </div>
                <label>
                  Категория причины
                  <select
                    aria-label="Категория причины"
                    value={reasonCode}
                    onChange={(e) => setReasonCode(e.target.value)}
                  >
                    <option value="">Выберите категорию</option>
                    {Object.entries(reasonCodeName)
                      .filter(([code]) => code !== "unspecified")
                      .map(([code, title]) => (
                        <option key={code} value={code}>
                          {title}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Причина решения
                  <textarea
                    placeholder="Что и почему изменено"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                </label>
                <div className="action-row">
                  <button
                    className="secondary"
                    disabled={busy || !reason.trim() || !reasonCode}
                    onClick={() => decide("reject")}
                  >
                    Отклонить проект
                  </button>
                  <button
                    className="primary"
                    disabled={busy || !reason.trim() || !reasonCode}
                    onClick={() => decide("edit_and_approve")}
                  >
                    Сохранить и подтвердить
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
