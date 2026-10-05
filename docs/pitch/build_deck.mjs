import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const here = path.dirname(new URL(import.meta.url).pathname);
const workspaceDir = path.resolve(here, "../..");
const SKILL_DIR = "/Users/sergej/.codex/plugins/cache/openai-primary-runtime/presentations/26.915.20218/skills/presentations";
const RUNTIME_PYTHON = "/Users/sergej/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";
const RUNTIME_NODE_MODULES = process.env.RUNTIME_NODE_MODULES ?? "/Users/sergej/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const { Presentation, PresentationFile } = await import(pathToFileURL(path.join(RUNTIME_NODE_MODULES,"@oai/artifact-tool/dist/artifact_tool.mjs")).href);
const { resolvePresentationFont, finalizePresentation } = await import(pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href);
const font = resolvePresentationFont();
const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const C = {
  dark: "#123B34", deeper: "#0C2B27", green: "#246653", mint: "#BDE5CF", pale: "#EAF5ED",
  ivory: "#F7F8F4", ink: "#173B34", muted: "#637E73", white: "#FFFFFF", line: "#D8E5DC",
  gold: "#D6A352", warm: "#FFF3DA", coral: "#C76B50", lightcoral: "#FAE7DF", blue: "#2F6B8A",
};

function shape(slide, geom, x, y, w, h, fill, stroke="none", lw=0, name="") {
  return slide.shapes.add({ geometry:geom, name, position:{left:x, top:y, width:w, height:h},
    fill, line:{style:"solid", fill:stroke, width:lw}, ...(geom === "roundRect" ? {borderRadius:"rounded-xl"} : {}) });
}
function text(slide, value, x, y, w, h, size=24, color=C.ink, bold=false, align="left", valign="top", name="") {
  const s=shape(slide,"textbox",x,y,w,h,"none","none",0,name);
  s.text=value;
  s.text.style={typeface:font,fontSize:size,bold,color,autoFit:"shrinkText"};
  s.text.alignment=align; s.text.verticalAlignment=valign; s.text.wrap="square";
  return s;
}
function line(slide,x1,y1,x2,y2,color=C.line,width=2) {
  if (Math.abs(y2-y1)<1) shape(slide,"rect",Math.min(x1,x2),y1,Math.abs(x2-x1),width,color);
  else if(Math.abs(x2-x1)<1) shape(slide,"rect",x1,Math.min(y1,y2),width,Math.abs(y2-y1),color);
}
function arrow(slide,x1,y,x2,color=C.green,width=3) {
  line(slide,x1,y,x2-12,y,color,width);
  shape(slide,"triangle",x2-15,y-7,16,14,color,"none",0).position.rotation=90;
}
function pill(slide,label,x,y,w,fill=C.pale,color=C.green) {
  shape(slide,"roundRect",x,y,w,30,fill);
  text(slide,label,x+9,y+4,w-18,23,14,color,true,"center","middle");
}
function card(slide,x,y,w,h,title,body,{fill=C.white,accent=C.green,bodySize=19,titleSize=23}={}) {
  shape(slide,"roundRect",x,y,w,h,fill,C.line,1);
  shape(slide,"rect",x,y,6,h,accent);
  text(slide,title,x+22,y+20,w-42,34,titleSize,C.ink,true);
  text(slide,body,x+22,y+62,w-42,h-72,bodySize,C.muted);
}
function base(title,section,num,{dark=false,subtitle=""}={}) {
  const s=p.slides.add(); s.background.fill=dark?C.dark:C.ivory;
  const fg=dark?C.white:C.ink;
  text(s,section.toUpperCase(),64,32,850,23,14,dark?C.mint:C.green,true);
  text(s,title,64,72,1150,78,42,fg,true);
  if(subtitle) text(s,subtitle,66,145,1110,50,20,dark?C.mint:C.muted);
  line(s,64,665,1216,665,dark?"#38675A":C.line,1);
  text(s,"meditron.  ·  синтетический прототип",64,678,600,22,13,dark?"#A9CBB9":C.muted);
  text(s,String(num).padStart(2,"0"),1160,677,55,23,13,dark?C.mint:C.muted,true,"right");
  return s;
}
function notes(s,v){s.speakerNotes.textFrame.setText(v);}

// 1: Product thesis.
{
 const s=base("От ИИ-заключения — к следующему шагу пациента","питч · 5 минут",1,{dark:true,subtitle:"Маршрут формируется и утверждается во время текущего приёма"});
 const items=["Обследование","ИИ / SR","Один следующий шаг","Решение специалиста","Запись и результат"];
 items.forEach((v,i)=>{
   const x=66+i*240;
   shape(s,"roundRect",x,290,212,112,i===2?C.mint:"#255247",i===2?C.mint:"#3B7062",1);
   text(s,String(i+1).padStart(2,"0"),x+18,308,48,26,16,i===2?C.green:C.mint,true);
   text(s,v,x+18,342,176,48,21,i===2?C.ink:C.white,true);
   if(i<4) arrow(s,x+213,346,x+237,C.mint,3);
 });
 text(s,"Мы не читаем снимок повторно. Мы превращаем уже готовое заключение в подтверждённое и измеримое действие.",72,475,1110,95,27,C.white,true);
 notes(s,"Исходный кейс пользователя: страницы 1–3 PDF «Кейс_Третье_мнение.pdf». Продуктовая формулировка и статус: docs/architecture.md, docs/implementation-status.md. Реальный uplift не измерен.");
}

// 2: The operating gap.
{
 const s=base("ИИ помогает описать находку. Дальнейший путь часто остаётся ручным","проблема",2,{subtitle:"Гипотеза роста: убрать разрыв между заключением, решением и записью"});
 card(s,64,225,335,286,"Уже есть в клинике","ИИ формирует дополнительную информацию и предварительно заполненный протокол исследования.",{fill:C.pale});
 card(s,465,225,335,286,"Операционный разрыв","Следующий шаг нужно выбрать, утвердить, объяснить и связать со свободным временем и результатом.",{fill:C.warm,accent:C.gold});
 card(s,866,225,350,286,"Потенциал","Меньше ручной передачи между ролями; выше шанс довести пациента до нужного действия.",{fill:C.pale});
 arrow(s,405,362,455,C.green);arrow(s,805,362,856,C.green);
 pill(s,"НЕИЗМЕРЕННАЯ ГИПОТЕЗА",64,554,265,C.lightcoral,C.coral);
 text(s,"В пилоте проверим каждое звено, а не будем приписывать потерям выдуманный процент.",352,550,815,48,20,C.muted);
 notes(s,"Источник описания уже применяемого ИИ: https://thirdopinion.ai/ (лучевая диагностика и предварительно заполненный протокол). Операционный разрыв сформулирован в предоставленном пользователем кейсе, страницы 1–2. Процент потерь неизвестен.");
}

// 3: Product architecture, not just integration.
{
 const s=base("Один следующий шаг соединяет решение и действие пациента","решение",3,{subtitle:"После результата создаётся новая связанная версия для следующего решения"});
 pill(s,"ВО ВРЕМЯ ПРИЁМА",64,214,232,C.pale,C.green);
 const tops=[
  ["1 · Разбор","Известные поля JSON / SR → общие факты"],
  ["2 · Правила","Один шаг + указатели на поля"],
  ["3 · Решение","Специалист подтверждает или правит с причиной"],
 ];
 tops.forEach((a,i)=>card(s,64+i*392,260,365,142,a[0],a[1],{bodySize:18,titleSize:22}));
 pill(s,"ПОСЛЕ ПРИЁМА",64,431,210,C.pale,C.green);
 const bottoms=[
  ["4 · Публикация","Пациент видит лишь утверждённый шаг"],
  ["5 · Запись / анализ","Подготовку можно организовать параллельно"],
  ["6 · Новый цикл","После результата снова решает специалист"],
 ];
 bottoms.forEach((a,i)=>card(s,64+i*392,475,365,138,a[0],a[1],{bodySize:17,titleSize:22,fill:C.white}));
 notes(s,"Принятое продуктовое решение: docs/architecture.md. В текущем синтетическом прототипе реализованы оба контура; клинические правила HYPOTHESIS, реальные внешние интеграции не готовы. По предоставленному БФТ поля JSON/SR структурированы, поэтому NLP в текущем пути не применяется.");
}

// 4: Compact BPMN view, formal model delivered separately.
{
 const s=base("BPMN: решение принимается до публикации пациенту","бизнес-процесс · часть 1",4,{subtitle:"Полная BPMN 2.0 модель с участниками и сообщениями — отдельный файл workflow.bpmn"});
 const ys=[232,337,442];const labels=["ИИ / источник","Meditron","Специалист"];
 ys.forEach((y,i)=>{shape(s,"roundRect",64,y,1152,92,i===1?C.pale:C.white,C.line,1);text(s,labels[i],78,y+28,148,40,18,C.green,true);line(s,226,y,226,y+92,C.line,2);});
 // Source pool.
 shape(s,"ellipse",282,259,32,32,C.mint,C.green,2);text(s,"SR готов",324,260,123,30,17,C.ink,true);
 arrow(s,451,275,493,C.green,2);shape(s,"roundRect",495,246,178,56,C.white,C.green,2);text(s,"Передать JSON / SR",508,254,153,44,17,C.ink,true,"center","middle");
 // Core lane, connections first.
 arrow(s,305,383,348);arrow(s,518,383,572);arrow(s,752,383,805);arrow(s,962,383,1015);
 shape(s,"ellipse",270,365,36,36,C.white,C.green,2);shape(s,"roundRect",348,351,170,62,C.white,C.green,2);text(s,"Разбор по профилю",360,361,146,40,17,C.ink,true,"center","middle");
 shape(s,"diamond",572,358,53,53,C.warm,C.gold,2);text(s,"?",589,369,20,26,20,C.gold,true,"center");
 text(s,"есть факты?",630,355,116,47,17,C.ink,true);shape(s,"roundRect",805,351,157,62,C.white,C.green,2);text(s,"Проект + trace",815,360,137,43,17,C.ink,true,"center","middle");
 shape(s,"roundRect",1015,351,161,62,C.white,C.green,2);text(s,"Получить решение",1025,360,141,43,17,C.ink,true,"center","middle");
 // Reviewer lane.
 shape(s,"roundRect",764,456,188,62,C.white,C.green,2);text(s,"Проверить основания",774,465,168,42,17,C.ink,true,"center","middle");
 arrow(s,953,487,1004);shape(s,"diamond",1005,462,52,52,C.warm,C.gold,2);text(s,"?",1021,474,20,25,20,C.gold,true,"center");
 text(s,"утвердить /\nисправить",1067,455,126,56,17,C.ink,true);
 line(s,875,413,875,455,C.green,2);line(s,1095,442,1095,414,C.green,2);
 pill(s,"без подтверждения: пациенту не показывать",64,572,395,C.lightcoral,C.coral);
 text(s,"Исправление создаёт новую версию и снова проходит проверку.",484,567,690,45,20,C.muted);
 notes(s,"Схема является сокращённым представлением формальной BPMN 2.0 модели docs/pitch/workflow.bpmn. Полная модель включает ручной путь при недостатке фактов, цикл исправления и отдельный пациентский процесс. Корректность правил пока не утверждена медицинским экспертом.");
}

// 5: Continuation and metrics.
{
 const s=base("После приёма путь продолжается по результату","бизнес-процесс · часть 2",5,{subtitle:"Один шаг, подготовка и новый проект после результата"});
 const y=255;
 const xs=[64,295,526,757,988], ts=["Показ шага","Выбор пациента","Запись / анализ","Результат шага","Новая версия"];
 const bs=["Только после\nподтверждения","Записаться / отказаться\nи вернуться","Анализ до приёма\nесли нужен","Факт и заключение\nпо услуге","Один новый шаг\nили завершение"];
 xs.forEach((x,i)=>{shape(s,"roundRect",x,y,194,150,i===4?C.pale:C.white,C.line,1);text(s,ts[i],x+16,y+21,162,43,20,C.ink,true);text(s,bs[i],x+16,y+78,162,62,17,C.muted);if(i<4)arrow(s,x+195,y+75,x+225);});
 shape(s,"roundRect",64,475,552,108,C.warm,C.gold,1);text(s,"Ключевой барьер",84,491,490,27,20,C.ink,true);text(s,"Следующий шаг появляется после результата и нового решения специалиста.",84,524,500,47,18,C.muted);
 shape(s,"roundRect",640,475,576,108,C.pale,C.line,1);text(s,"Измеряемый след",660,491,520,27,20,C.ink,true);text(s,"Показ → запрос → подтверждение → визит; отказ и возврат отдельно.",660,524,525,47,18,C.muted);
 notes(s,"Продуктовый workflow: docs/architecture.md, docs/implementation-status.md. Валовая синтетическая конверсия в коде считается до подтверждённой записи, не до фактического визита; uplift неизвестен. Файл docs/pitch/workflow.bpmn содержит вторую формальную BPMN-диаграмму продолжения.");
}

// 6: Existing prototype proof.
{
 const s=base("Работает синтетический сквозной прототип","готовность",6,{subtitle:"Проверяем поведение на воспроизводимых сценариях, не заявляя клиническую готовность"});
 const img=await fs.readFile(path.join(workspaceDir,"frontend/test-results/reviewer.png"));
 s.images.add({blob:new Uint8Array(img),contentType:"image/png",alt:"Синтетический экран специалиста Meditron",fit:"cover",crop:{left:0.14,top:0.1,right:0,bottom:0.2},position:{left:64,top:225,width:655,height:380},geometry:"roundRect",borderRadius:"rounded-xl"});
 const metrics=[["JSON + SR","2 входных представления"],["7 пар","синтетических заключений"],["110 + 8","backend и браузерных тестов"]];
 metrics.forEach((m,i)=>{shape(s,"roundRect",756,225+i*129,460,111,C.white,C.line,1);text(s,m[0],778,240+i*129,400,45,31,C.green,true);text(s,m[1],778,286+i*129,400,34,17,C.muted);});
 pill(s,"HYPOTHESIS: медицинская матрица",64,622,352,C.warm,C.coral);
 notes(s,"Фактический статус на 04.10.2026: docs/implementation-status.md и docs/evaluation-results-synthetic.json. 110 backend тестов, 8 браузерных; семь пар JSON/SR. Изображение: frontend/test-results/reviewer.png, снято на синтетическом демо. Реальные Kafka/PACS/МИС и клиническая валидация отсутствуют.");
}

// 7: Market, competitors, business model.
{
 const s=base("Покупатель — клиника с ИИ и потоком следующих действий","рынок и бизнес-модель",7,{subtitle:"Мы встраиваемся между поставщиком заключения, специалистом и системой записи"});
 text(s,"Публичный сигнал: «Третье Мнение» сообщает о 10 млн обработанных исследований и работе в 58 регионах. Это не TAM Meditron.",66,191,1148,33,16,C.muted);
 const cols=[64,355,646,937];const heads=["ИИ диагностики","МИС / запись","CDS / аналитика","Meditron"];
 const bodies=["Готовое описание и SR. Поставщик может развивать маршрутизацию.","Расписание, слоты, коммуникации и факт услуги.","Поддержка решений на широких данных пациента.","Исполнение маршрута из SR: версии, решение, запись, результат."];
 cols.forEach((x,i)=>card(s,x,232,267,240,heads[i],bodies[i],{bodySize:17,titleSize:20,fill:i===3?C.pale:C.white,accent:i===3?C.green:C.gold}));
 shape(s,"roundRect",64,509,552,109,C.white,C.line,1);text(s,"Частная клиника",86,523,500,30,21,C.ink,true);text(s,"Настройка + абонентская плата; эффект — запись и визит.",86,557,505,50,18,C.muted);
 shape(s,"roundRect",640,509,576,109,C.white,C.line,1);text(s,"Государственная клиника",662,523,530,30,21,C.ink,true);text(s,"Внедрение + сопровождение; эффект — завершение пути и время.",662,557,530,50,18,C.muted);
 notes(s,"Рынок сегментирован по задаче, численный TAM не утверждается. 10 млн исследований и 58 регионов — самоописание «Третьего Мнения» на https://thirdopinion.ai/ по состоянию на 04.10.2026, не объём доступного рынка или годовой поток. Платформенный вектор: https://thirdopinion.ai/tpost/5s66ygpj11-orgzdrav-2026-anna-mescheryakova-o-platf. Смежные продукты: https://www.medesk.ru/ (МИС и запись), https://webiomed.ru/ (аналитика/CDS). Это сравнение категорий, не доказательство отсутствия функциональности у конкурентов. Цены являются гипотезой.");
}

// 8: Unit economics with explicit assumptions.
{
 const s=base("Экономику определяет измеренный прирост завершённых действий","unit-экономика · сценарий",8,{subtitle:"Иллюстрация на одну частную площадку в месяц; цены и uplift пока не подтверждены"});
 const chips=[["800","подходящих SR"],["+3 п.п.","гипотетический uplift"],["80%","дошли до визита"],["2 500 ₽","вклад визита"]];
 chips.forEach((m,i)=>{const x=64+i*291;shape(s,"roundRect",x,222,267,122,C.white,C.line,1);text(s,m[0],x+18,238,230,42,30,C.green,true);text(s,m[1],x+18,284,230,43,17,C.muted);});
 text(s,"800 × 3% × 80% × 2 500 ₽  =  48 000 ₽ / мес.",74,386,1130,58,35,C.ink,true);
 text(s,"При условной плате 30 000 ₽: порог для клиники = 1,875 п.п.",74,456,1105,48,23,C.muted);
 const bars=[{lab:"+1 п.п.",v:16000},{lab:"+3 п.п.",v:48000},{lab:"+5 п.п.",v:80000}];
 bars.forEach((b,i)=>{const y=531+i*35;text(s,b.lab,74,y-4,118,26,17,C.ink,true);shape(s,"rect",206,y,Math.round(b.v/80000*620),20,i===0?C.gold:C.green);text(s,(b.v/1000)+" тыс. ₽",846,y-6,180,30,17,C.ink,true);});
 text(s,"Без стоимости интеграции, загрузки врача, отмен и ограничений ёмкости.",74,642,1040,20,14,C.coral);
 notes(s,"Все значения на слайде являются допущениями, а не результатом пилота. Полная формула и чувствительность: docs/pitch/economics.json. Реальная конверсия и uplift не измерены. Валовая метрика прототипа: docs/implementation-status.md. Чтобы приписывать причинный эффект, нужна контрольная группа. Для госучреждений финансовая логика и закупка отличаются.");
}

// 9: Roadmap.
{
 const s=base("Внедрение идёт через доказательства, а не через календарные обещания","дорожная карта",9,{subtitle:"Каждый этап открывается только после проверки предыдущего"});
 const stages=[
  ["0","MVP","Синтетика, два контура, тесты","Выполнено"],
  ["1","Контракты","Реальные SR, коды услуг, экспертная матрица","Согласовать"],
  ["2","Теневой режим","Разбор без публикации; полнота и время","Измерить"],
  ["3","Пилот","Один поток, запись, контрольная группа","Проверить"],
  ["4","Масштаб","Новые профили и типы учреждений","Повторить"],
 ];
 stages.forEach((a,i)=>{const x=64+i*233;shape(s,"roundRect",x,247,210,292,i===0?C.pale:C.white,C.line,1);pill(s,a[0],x+16,265,40,i===0?C.green:C.pale,i===0?C.white:C.green);text(s,a[1],x+16,311,177,38,22,C.ink,true);text(s,a[2],x+16,361,177,106,17,C.muted);line(s,x+16,490,x+194,490,C.line,1);text(s,a[3],x+16,501,177,26,16,i===0?C.green:C.coral,true);if(i<4)arrow(s,x+212,392,x+229);});
 text(s,"Гейт пилота: клиническая матрица, контрактные тесты, статус записи, безопасная публикация, метод оценки uplift.",64,572,1120,62,20,C.ink,true);
 notes(s,"Этап 0 соответствует текущему синтетическому прототипу: docs/implementation-status.md. Этапы 1–4 являются планом, сроки зависят от доступности партнёрских контрактов и медицинского эксперта. Дорожная карта подробнее: docs/pitch/diagrams.md.");
}

// 10: Team, risks, ask.
{
 const s=base("Следующий шаг — совместная проверка в клинике","команда · риски · запрос",10,{subtitle:"Состав команды по ролям; имена и подтверждённый опыт заполняются после согласования"});
 const roles=["Клинический эксперт","Backend / интеграции","Product / UX","Аналитика / PM"];
 roles.forEach((v,i)=>{const x=64+i*291;shape(s,"roundRect",x,231,267,91,C.pale,C.line,1);text(s,v,x+16,248,235,58,20,C.ink,true,"center","middle");});
 shape(s,"roundRect",64,360,552,210,C.white,C.line,1);text(s,"Риски для пилота",86,379,500,35,23,C.ink,true);
 text(s,"• Правила не утверждены экспертом\n• SR может прийти после завершения приёма\n• Контракт записи и реальные статусы неизвестны",86,423,510,125,18,C.muted);
 shape(s,"roundRect",640,360,576,210,C.white,C.line,1);text(s,"Что нужно от партнёра",662,379,530,35,23,C.ink,true);
 text(s,"• Обезличенные примеры JSON / SR\n• Каталог услуг и тестовый контур записи\n• Эксперт матрицы и согласие на пилотную оценку",662,423,530,125,18,C.muted);
 text(s,"Сегодня мы доказываем исполнимость процесса на синтетике. Следом проверим клиническую пригодность и реальный эффект.",66,596,1140,47,23,C.green,true);
 notes(s,"Исходный кейс перечисляет востребованные роли, но фактический состав команды, имена и индивидуальные достижения не сообщены пользователем. Не выдавать эти роли за уже нанятую команду. Риски и статус прототипа: docs/architecture.md и docs/implementation-status.md. Запрос к партнёру предложен как следующий этап.");
}

const buildDir=path.join(workspaceDir,".codex-pitch-build");
await fs.mkdir(buildDir,{recursive:true});
const candidatePath=path.join(buildDir,"candidate.pptx");
await (await PresentationFile.exportPptx(p)).save(candidatePath);
const finalPath=path.join(here,"meditron-pitch-v3.pptx");
const result=await finalizePresentation({
  workspaceDir,candidatePath,finalPath,
  pythonExecutable:RUNTIME_PYTHON,
  integrityValidatorPath:path.join(SKILL_DIR,"container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath:path.join(SKILL_DIR,"container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs:["--expected-slide-size-emu","12192000,6858000","--validate-heading-fit"],
  requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
  fontPolicy:{basis:"design",families:[font]},verifyArtifactToolImport:true,
  receiptPath:path.join(buildDir,"validation-v3.json"),
});
console.log(JSON.stringify({font,final:finalPath,result},null,2));
