import {
  cloneElement,
  isValidElement,
  useId,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type ReactElement,
} from "react";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Download,
  FolderInput,
  History,
  Layers3,
  LogOut,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sparkles,
  Users,
  X,
  LockKeyhole,
  Check,
  AlertCircle,
  Clock3,
  ArrowRightLeft,
  Pencil,
  Trash2,
} from "lucide-react";

type Item = Record<string, any>;
type College = {
  settings: Item;
  teachers: Record<string, Item>;
  groups: Record<string, Item>;
  rooms: Record<string, Item>;
  subjects: Record<string, Item>;
  requirements: Record<string, Item>;
  lessons: Record<string, Item>;
  plans: Record<string, Item>;
};
type Payload = { version: number; state: College };
type Auth = { name: string; login: string; csrf: string };
const labels: Record<string, string> = {
  theory: "Теория",
  practice: "Практика",
  consultation: "Консультация",
  assessment: "Аттестация",
  training: "Практика УП/ПП",
  coursework: "Курсовая работа",
};
const catalogs: Record<string, string> = {
  teachers: "Преподаватели",
  groups: "Группы",
  rooms: "Помещения",
  subjects: "Дисциплины",
};
const days = [
  "Понедельник",
  "Вторник",
  "Среда",
  "Четверг",
  "Пятница",
  "Суббота",
  "Воскресенье",
];
const uid = () => crypto.randomUUID().replaceAll("-", "");
const clock = (n: number) =>
  `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;
const minutes = (s: string) => {
  const [h, m] = s.split(":").map(Number);
  return h * 60 + m;
};
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const todayWeek = () => {
  const d = new Date();
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return iso(d);
};
const shift = (s: string, n: number) => {
  const d = new Date(s + "T12:00:00");
  d.setDate(d.getDate() + n);
  return iso(d);
};
const dateLabel = (s: string) =>
  new Date(s + "T12:00:00").toLocaleDateString("ru", {
    day: "numeric",
    month: "long",
  });
const names = (data: Record<string, Item>, ids: string[]) =>
  ids.map((id) => data[id]?.name ?? "Запись удалена").join(", ");

function Button({
  children,
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button className={`button ${className}`} {...props}>
      {children}
    </button>
  );
}
function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  const labelId = useId();
  const child = children as ReactElement<any>;
  const control = isValidElement(children)
    ? child.type === Pick
      ? cloneElement(child, { labelledBy: labelId })
      : ["input", "select", "textarea"].includes(child.type as string)
        ? cloneElement(child, { "aria-labelledby": labelId })
        : children
    : children;
  return (
    <div className="field">
      <span id={labelId}>{label}</span>
      {control}
      {hint && <small>{hint}</small>}
    </div>
  );
}
function Pick({
  value,
  onChange,
  items,
  empty = "Выберите",
  disabled = false,
  labelledBy,
}: {
  value: string;
  onChange: (v: string) => void;
  items: Item[];
  empty?: string;
  disabled?: boolean;
  labelledBy?: string;
}) {
  return (
    <select
      aria-labelledby={labelledBy}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{empty}</option>
      {items.map((x) => (
        <option value={x.id} key={x.id}>
          {x.name}
        </option>
      ))}
    </select>
  );
}
function Multi({
  items,
  value,
  onChange,
}: {
  items: Item[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div className="multi">
      {!items.length && <small>Сначала добавьте записи в справочник.</small>}
      {items.map((x) => (
        <label key={x.id} className={value.includes(x.id) ? "selected" : ""}>
          <input
            type="checkbox"
            checked={value.includes(x.id)}
            onChange={(e) =>
              onChange(
                e.target.checked
                  ? [...value, x.id]
                  : value.filter((id) => id !== x.id),
              )
            }
          />
          {x.name}
        </label>
      ))}
    </div>
  );
}
function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  return (
    <div
      className="scrim"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className={`modal ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <h2>{title}</h2>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            aria-label="Закрыть"
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
function Notice({
  children,
  error = false,
}: {
  children: ReactNode;
  error?: boolean;
}) {
  return (
    <div className={`notice ${error ? "error" : ""}`}>
      <AlertCircle size={18} />
      <div>{children}</div>
    </div>
  );
}

export default function App() {
  const [auth, setAuth] = useState<Auth | null>(null),
    [data, setData] = useState<Payload | null>(null),
    [loaded, setLoaded] = useState(false);
  const [page, setPage] = useState("schedule"),
    [week, setWeek] = useState(todayWeek()),
    [error, setError] = useState(""),
    [success, setSuccess] = useState("");
  const [editing, setEditing] = useState(false),
    [stale, setStale] = useState(false);
  const editingRef = useRef(false);
  editingRef.current = editing;
  const authRef = useRef<Auth | null>(auth);
  authRef.current = auth;
  const api = useCallback(async (path: string, options: RequestInit = {}) => {
    const headers = new Headers(options.headers);
    if (!(options.body instanceof FormData) && options.body)
      headers.set("Content-Type", "application/json");
    if (authRef.current) headers.set("X-CSRF-Token", authRef.current.csrf);
    const r = await fetch("/api" + path, {
      ...options,
      headers,
      credentials: "same-origin",
    });
    const result = await r
      .json()
      .catch(() => ({ detail: "Не удалось прочитать ответ сервера" }));
    if (!r.ok) {
      if (r.status === 401 && path != "/auth/login") {
        setAuth(null);
        setData(null);
      }
      const detail = result.detail;
      throw new Error(
        Array.isArray(detail)
          ? detail.map((x) => (typeof x === "string" ? x : x.msg)).join("; ")
          : (detail ?? "Ошибка запроса"),
      );
    }
    return result;
  }, []);
  const refresh = useCallback(async () => {
    const p = await api("/state");
    setData(p);
    setStale(false);
  }, [api]);
  useEffect(() => {
    api("/auth/me")
      .then(async (a) => {
        authRef.current = a;
        setAuth(a);
        await refresh();
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [api, refresh]);
  useEffect(() => {
    if (!auth) return;
    const timer = setInterval(async () => {
      try {
        const p = await api("/state");
        setData((old) => {
          if (old && p.version !== old.version && editingRef.current) {
            setStale(true);
            return old;
          }
          return p;
        });
      } catch {}
    }, 15000);
    return () => clearInterval(timer);
  }, [auth, api]);
  useEffect(() => {
    if (!success) return;
    const t = setTimeout(() => setSuccess(""), 4500);
    return () => clearTimeout(t);
  }, [success]);
  const save = async (path: string, body: unknown, method = "PUT") => {
    setError("");
    try {
      await api(path, { method, body: JSON.stringify(body) });
      await refresh();
      setSuccess("Изменения сохранены");
      return true;
    } catch (e) {
      setError((e as Error).message);
      throw e;
    }
  };
  const closeErrors = () => {
    setError("");
    setStale(false);
  };
  if (!loaded)
    return (
      <div className="loading">
        <CalendarDays />
        Загрузка приложения…
      </div>
    );
  if (!auth)
    return (
      <Login
        onLogin={async (login, password) => {
          const a = await api("/auth/login", {
            method: "POST",
            body: JSON.stringify({ login, password }),
          });
          authRef.current = a;
          setAuth(a);
          await refresh();
        }}
      />
    );
  if (!data) return <div className="loading">Загрузка данных…</div>;
  const state = data.state;
  const views = [
    ["schedule", "Расписание", CalendarDays],
    ["load", "Нагрузка", Layers3],
    ["catalog", "Справочники", Users],
    ["import", "Импорт документов", FolderInput],
    ["history", "История", History],
    ["settings", "Настройки", Settings2],
  ] as const;
  const editor = (flag: boolean) => {
    setEditing(flag);
    if (!flag) closeErrors();
  };
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-icon">
            <CalendarDays size={23} />
          </span>
          <div>
            <b>Расписание</b>
            <small>Колледж · рабочая область</small>
          </div>
        </div>
        <div className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
        <nav>
          {views.map(([key, title, Icon]) => (
            <button
              key={key}
              className={page === key ? "active" : ""}
              onClick={() => {
                setPage(key);
                editor(false);
              }}
            >
              <Icon size={19} />
              {title}
              {key === "load" && (
                <span className="nav-count">
                  {Object.keys(state.requirements).length}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <ShieldCheck size={18} />
          <div>
            Общие данные<small>Изменения сохраняются на сервере</small>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>{state.settings.name}</span>
          <div className="user">
            <span className="avatar">{auth.name[0]?.toUpperCase()}</span>
            <div>
              <b>{auth.name}</b>
              <small>{auth.login}</small>
            </div>
            <button
              className="icon-button"
              title="Выйти"
              onClick={async () => {
                await api("/auth/logout", { method: "POST" });
                setAuth(null);
                setData(null);
              }}
            >
              <LogOut size={17} />
            </button>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">УЧЕБНОЕ ПЛАНИРОВАНИЕ</div>
              <h1>{views.find((x) => x[0] === page)?.[1]}</h1>
            </div>
            <span className="saved">
              <span />
              Версия {data.version}
            </span>
          </div>
          {error && (
            <Notice error>
              {error}
              <button className="text-button" onClick={() => setError("")}>
                Скрыть
              </button>
            </Notice>
          )}
          {success && (
            <div className="toast">
              <Check size={16} />
              {success}
            </div>
          )}
          {stale && (
            <Notice>
              Другой пользователь изменил данные. Закройте форму и обновите
              страницу перед новой правкой.
            </Notice>
          )}
          {page === "schedule" && (
            <Schedule
              state={state}
              version={data.version}
              week={week}
              setWeek={setWeek}
              api={api}
              save={save}
              refresh={refresh}
              editor={editor}
            />
          )}
          {page === "catalog" && (
            <Catalog
              state={state}
              version={data.version}
              save={save}
              editor={editor}
            />
          )}
          {page === "load" && (
            <Load
              state={state}
              version={data.version}
              week={week}
              setWeek={setWeek}
              save={save}
              editor={editor}
            />
          )}
          {page === "settings" && (
            <CalendarSettings
              state={state}
              version={data.version}
              save={save}
              editor={editor}
            />
          )}
          {page === "import" && (
            <Imports
              state={state}
              version={data.version}
              api={api}
              save={save}
              week={week}
              editor={editor}
            />
          )}
          {page === "history" && (
            <HistoryView api={api} save={save} version={data.version} />
          )}
        </main>
        <footer>
          Расписание колледжа
          <span>Часы, группы и ресурсы в одном рабочем пространстве</span>
        </footer>
      </div>
    </div>
  );
}

type Save = (path: string, body: unknown, method?: string) => Promise<boolean>;
type Api = (path: string, options?: RequestInit) => Promise<any>;
type Common = {
  state: College;
  version: number;
  save: Save;
  editor: (v: boolean) => void;
};
function Login({
  onLogin,
}: {
  onLogin: (login: string, password: string) => Promise<void>;
}) {
  const [login, setLogin] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <div className="login-art">
        <span className="login-mark">
          <CalendarDays size={40} />
        </span>
        <h1>
          Учебная неделя.
          <br />
          Всё на своих местах.
        </h1>
        <p>Составляйте расписание, учитывайте нагрузку и работайте вместе.</p>
        <div className="abstract-calendar">
          {Array.from({ length: 20 }, (_, i) => (
            <span
              key={i}
              className={i % 5 === 0 ? "blue" : i % 3 === 0 ? "light" : ""}
            />
          ))}
        </div>
        <small>Расписание колледжа</small>
      </div>
      <section className="login-card">
        <div className="eyebrow">ДОСТУП ДЛЯ СОТРУДНИКОВ</div>
        <h2>Вход в приложение</h2>
        <p>Используйте свой логин и пароль.</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await onLogin(login, password);
            } catch (x) {
              setError((x as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="Логин">
            <input
              autoComplete="username"
              autoFocus
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              required
            />
          </Field>
          <Field label="Пароль">
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
          {error && <Notice error>{error}</Notice>}
          <Button className="primary full" disabled={busy}>
            {busy ? "Входим…" : "Войти"}
            <ChevronRight size={17} />
          </Button>
        </form>
        <small className="login-help">
          <LockKeyhole size={14} />
          Доступ только для сотрудников колледжа
        </small>
      </section>
    </div>
  );
}

function WeekControl({
  week,
  onChange,
}: {
  week: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="week-control">
      <button
        className="icon-button"
        aria-label="Предыдущая неделя"
        onClick={() => onChange(shift(week, -7))}
      >
        <ChevronLeft size={18} />
      </button>
      <span>
        <CalendarDays size={17} />
        {dateLabel(week)} – {dateLabel(shift(week, 4))}
      </span>
      <button
        className="icon-button"
        aria-label="Следующая неделя"
        onClick={() => onChange(shift(week, 7))}
      >
        <ChevronRight size={18} />
      </button>
      <Button onClick={() => onChange(todayWeek())}>Сегодня</Button>
    </div>
  );
}
function groupCovers(state: College, ids: string[], gid: string): boolean {
  let current: string | undefined = gid;
  const seen = new Set<string>();
  while (current && !seen.has(current)) {
    if (ids.includes(current)) return true;
    seen.add(current);
    current = state.groups[current]?.parent_id;
  }
  return false;
}

function Schedule({
  state,
  version,
  week,
  setWeek,
  api,
  save,
  refresh,
  editor,
}: Common & {
  week: string;
  setWeek: (v: string) => void;
  api: Api;
  refresh: () => Promise<void>;
}) {
  const [group, setGroup] = useState(""),
    [teacher, setTeacher] = useState(""),
    [modal, setModal] = useState<Item | null>(null),
    [generation, setGeneration] = useState(false),
    [check, setCheck] = useState<Item | null>(null),
    [swapping, setSwapping] = useState(false);
  const groups = Object.values(state.groups).filter(
    (g) =>
      !Object.values(state.groups).some((x) => x.parent_id === g.id) &&
      (!group || groupCovers(state, [group], g.id)),
  );
  const lessons = Object.values(state.lessons).filter(
    (l) =>
      l.day >= week &&
      l.day < shift(week, 7) &&
      (!teacher || l.teacher_ids.includes(teacher)) &&
      (!group ||
        l.group_ids.some(
          (g: string) =>
            groupCovers(state, [group], g) || groupCovers(state, [g], group),
        )),
  );
  const placed = Object.values(state.requirements).filter(
    (r) =>
      r.week === week &&
      (!teacher || r.teacher_ids.includes(teacher)) &&
      (!group ||
        r.group_ids.some(
          (g: string) =>
            groupCovers(state, [group], g) || groupCovers(state, [g], group),
        )),
  );
  const planned = placed.reduce((n, r) => n + r.hours, 0),
    actual = lessons
      .filter((l) => l.requirement_id)
      .reduce((n, l) => n + l.hours, 0);
  const open = (l: Item) => {
    setModal(l);
    editor(true);
  };
  const close = () => {
    setModal(null);
    editor(false);
  };
  return (
    <>
      <div className="stats">
        <div>
          <span>Занятий на неделе</span>
          <b>{lessons.length}</b>
          <small>В выбранном представлении</small>
        </div>
        <div>
          <span>Плановые часы</span>
          <b>
            {planned}
            <em>акад. ч.</em>
          </b>
          <small>По подтверждённой нагрузке</small>
        </div>
        <div>
          <span>Размещённые часы</span>
          <b>
            {actual}
            <em>акад. ч.</em>
          </b>
          <small>Часы связанных занятий</small>
        </div>
        <div className="stats-accent">
          <span>Совместная работа</span>
          <b>
            4<em>пользователя</em>
          </b>
          <small>Отдельные логины, общие данные</small>
        </div>
      </div>
      <div className="panel schedule-panel">
        <div className="toolbar">
          <WeekControl week={week} onChange={setWeek} />
          <div className="actions">
            <Button onClick={() => open({})}>
              <Plus size={16} />
              Занятие
            </Button>
            <Button
              className="primary"
              onClick={() => {
                setGeneration(true);
                editor(true);
              }}
            >
              <Sparkles size={16} />
              Сформировать
            </Button>
          </div>
        </div>
        <div className="filterbar">
          <Pick
            items={Object.values(state.groups)}
            value={group}
            onChange={setGroup}
            empty="Все группы"
          />
          <Pick
            items={Object.values(state.teachers)}
            value={teacher}
            onChange={setTeacher}
            empty="Все преподаватели"
          />
          <div className="filter-actions">
            <Button
              onClick={async () => setCheck(await api("/check?week=" + week))}
            >
              <ShieldCheck size={16} />
              Проверить
            </Button>
            <Button
              onClick={() => {
                setSwapping(true);
                editor(true);
              }}
              title="Поменять два занятия местами"
            >
              <ArrowRightLeft size={16} />
            </Button>
            <button
              className="icon-button"
              aria-label="Обновить расписание"
              onClick={refresh}
            >
              <RefreshCw size={17} />
            </button>
            <a
              className="button"
              href={`/api/export.xlsx?week=${week}${group ? "&group_ids=" + group : ""}`}
            >
              <Download size={16} />
              Excel
            </a>
          </div>
        </div>
        {!groups.length ? (
          <div className="empty">
            <CalendarDays size={38} />
            <h3>Добавьте учебные группы</h3>
            <p>Создайте справочники, загрузите КУГ и подтвердите нагрузку.</p>
          </div>
        ) : (
          <div className="grid-scroll">
            <table className="schedule-grid">
              <thead>
                <tr>
                  <th className="time-column">День / пара</th>
                  {groups.map((g) => (
                    <th key={g.id}>
                      <b>{g.name}</b>
                      <small>{g.stream || g.program}</small>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {state.settings.study_days.flatMap((weekday: number) => {
                  const day = shift(week, weekday),
                    bells = [...state.settings.bells].sort(
                      (a, b) => a.start - b.start,
                    ),
                    covered = new Set<string>();
                  return bells.map((bell: Item, bi: number) => (
                    <tr
                      key={day + bell.number}
                      className={bi === 0 ? "day-start" : ""}
                    >
                      <th className="time-column">
                        {bi === 0 && (
                          <strong>
                            {days[weekday]}
                            <small>{dateLabel(day)}</small>
                          </strong>
                        )}
                        <span>{bell.number} пара</span>
                        <small>
                          {clock(bell.start)} – {clock(bell.end)}
                        </small>
                      </th>
                      {groups.map((g, gi) => {
                        if (covered.has(`${bi}:${gi}`)) return null;
                        const active = lessons
                          .filter(
                            (l) =>
                              l.day === day &&
                              l.start < bell.end &&
                              l.end > bell.start &&
                              groupCovers(state, l.group_ids, g.id),
                          )
                          .sort((a, b) => a.start - b.start);
                        let span = 1,
                          rowSpan = 1;
                        if (active.length === 1) {
                          const l = active[0];
                          while (
                            gi + span < groups.length &&
                            groupCovers(
                              state,
                              l.group_ids,
                              groups[gi + span].id,
                            ) &&
                            lessons.filter(
                              (x) =>
                                x.day === day &&
                                x.start < bell.end &&
                                x.end > bell.start &&
                                groupCovers(
                                  state,
                                  x.group_ids,
                                  groups[gi + span].id,
                                ),
                            ).length === 1
                          )
                            span++;
                          if (l.start <= bell.start)
                            while (
                              bi + rowSpan < bells.length &&
                              bells[bi + rowSpan].start < l.end &&
                              groups
                                .slice(gi, gi + span)
                                .every(
                                  (column) =>
                                    lessons.filter(
                                      (x) =>
                                        x.day === day &&
                                        x.start < bells[bi + rowSpan].end &&
                                        x.end > bells[bi + rowSpan].start &&
                                        groupCovers(
                                          state,
                                          x.group_ids,
                                          column.id,
                                        ),
                                    ).length === 1,
                                )
                            )
                              rowSpan++;
                          for (let r = bi; r < bi + rowSpan; r++)
                            for (let c = gi; c < gi + span; c++)
                              if (r !== bi || c !== gi)
                                covered.add(`${r}:${c}`);
                        }
                        return (
                          <td key={g.id} colSpan={span} rowSpan={rowSpan}>
                            {active.map((l) => (
                              <button
                                key={l.id}
                                data-lesson-id={l.id}
                                className={`lesson ${l.kind}`}
                                onClick={() => open(l)}
                              >
                                <div className="lesson-top">
                                  <span>{labels[l.kind]}</span>
                                  {l.locked && <LockKeyhole size={12} />}
                                </div>
                                <b>{state.subjects[l.subject_id]?.name}</b>
                                <span>
                                  {names(state.teachers, l.teacher_ids)}
                                </span>
                                <small>
                                  {state.rooms[l.room_id]?.name} ·{" "}
                                  {clock(l.start)}–{clock(l.end)}
                                </small>
                                {span > 1 && (
                                  <small className="shared">
                                    Общее занятие · {l.group_ids.length} группы
                                  </small>
                                )}
                              </button>
                            ))}
                            {!active.length && (
                              <button
                                className="empty-cell"
                                aria-label={`Добавить занятие ${g.name}, ${day}, пара ${bell.number}`}
                                onClick={() =>
                                  open({
                                    group_ids: [g.id],
                                    day,
                                    start: bell.start,
                                    end: bell.end,
                                    hours: bell.hours,
                                  })
                                }
                              >
                                <Plus size={15} />
                              </button>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ));
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="grid-legend">
          <span className="dot blue" />
          Теория
          <span className="dot green" />
          Практика
          <span className="dot amber" />
          Аттестация
          <span className="legend-right">
            <LockKeyhole size={13} />
            Закреплённые занятия сохраняются при генерации
          </span>
        </div>
      </div>
      {modal && (
        <LessonEditor
          state={state}
          version={version}
          item={modal}
          save={save}
          onClose={close}
          week={week}
        />
      )}{" "}
      {generation && (
        <Generator
          state={state}
          version={version}
          week={week}
          api={api}
          save={save}
          onClose={() => {
            setGeneration(false);
            editor(false);
          }}
        />
      )}
      {check && (
        <Modal title="Проверка расписания" onClose={() => setCheck(null)} wide>
          <div className="modal-body">
            {check.complete ? (
              <div className="notice good">
                <ShieldCheck />
                Все плановые часы размещены, обязательные проверки пройдены.
              </div>
            ) : (
              <Notice>
                Расписание требует проверки или заполнения оставшихся часов.
              </Notice>
            )}
            {[...check.errors, ...check.warnings].map(
              (x: string, i: number) => (
                <p key={i} className="check-note">
                  {x}
                </p>
              ),
            )}
            <table className="data-table">
              <thead>
                <tr>
                  <th>Предмет</th>
                  <th>План</th>
                  <th>Размещено</th>
                  <th>Остаток</th>
                </tr>
              </thead>
              <tbody>
                {check.hours.map((r: Item) => (
                  <tr key={r.id}>
                    <td>{r.subject}</td>
                    <td>{r.hours}</td>
                    <td>{r.scheduled}</td>
                    <td>
                      <b className={r.remaining ? "amber-text" : "green-text"}>
                        {r.remaining}
                      </b>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Modal>
      )}
      {swapping && (
        <Swap
          state={state}
          version={version}
          save={save}
          week={week}
          onClose={() => {
            setSwapping(false);
            editor(false);
          }}
        />
      )}
    </>
  );
}

function Catalog({ state, version, save, editor }: Common) {
  const [kind, setKind] = useState("teachers"),
    [item, setItem] = useState<Item | null>(null),
    [query, setQuery] = useState("");
  const collection = state[kind as keyof College] as Record<string, Item>;
  const items = Object.values(collection).filter((x) =>
    x.name.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <>
      <div className="tabs">
        {Object.entries(catalogs).map(([key, title]) => (
          <button
            className={kind === key ? "active" : ""}
            onClick={() => setKind(key)}
            key={key}
          >
            {title}
            <span>{Object.keys(state[key as keyof College]).length}</span>
          </button>
        ))}
      </div>
      <div className="panel">
        <div className="toolbar">
          <input
            className="search"
            placeholder="Найти по названию…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Button
            className="primary"
            onClick={() => {
              setItem({});
              editor(true);
            }}
          >
            <Plus size={16} />
            Добавить
          </Button>
        </div>
        {!items.length ? (
          <div className="empty">
            <Users size={32} />
            <h3>Справочник пока пуст</h3>
            <p>
              Добавьте записи, чтобы использовать их в нагрузке и расписании.
            </p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Наименование</th>
                <th>Сведения</th>
                <th>Доступность</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((x) => (
                <tr key={x.id}>
                  <td>
                    <b>{x.name}</b>
                    {kind === "rooms" && <small>{x.building}</small>}
                  </td>
                  <td>
                    {kind === "groups"
                      ? `${x.program || "Программа не указана"} · ${x.course} курс · база ${x.base}`
                      : kind === "teachers"
                        ? `${x.max_day_hours ?? "Без лимита"} ч./день · ${x.max_week_hours ?? "без лимита"} ч./нед.`
                        : kind === "rooms"
                          ? `${{ classroom: "Аудитория", lab: "Лаборатория", gym: "Спортзал", clinic: "Клиническая база" }[x.kind as string]} · ${x.parallel_capacity} занятий одновременно`
                          : x.code || "Код не указан"}
                  </td>
                  <td>
                    {x.windows?.length
                      ? "По указанным часам"
                      : "Все учебные часы"}
                  </td>
                  <td className="table-actions">
                    <button
                      className="icon-button"
                      aria-label={`Редактировать ${x.name}`}
                      onClick={() => {
                        setItem(x);
                        editor(true);
                      }}
                    >
                      <Pencil size={16} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label={`Удалить ${x.name}`}
                      onClick={async () => {
                        if (
                          window.confirm(
                            `Удалить «${x.name}»? Используемые записи удалить нельзя.`,
                          )
                        )
                          try {
                            await save(
                              `/catalog/${kind}/${x.id}?version=${version}`,
                              undefined,
                              "DELETE",
                            );
                          } catch {}
                      }}
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {item && (
        <CatalogEditor
          state={state}
          kind={kind}
          version={version}
          item={item}
          save={save}
          onClose={() => {
            setItem(null);
            editor(false);
          }}
        />
      )}
    </>
  );
}

function CatalogEditor({
  state,
  kind,
  version,
  item,
  save,
  onClose,
}: {
  state: College;
  kind: string;
  version: number;
  item: Item;
  save: Save;
  onClose: () => void;
}) {
  const [form, setForm] = useState<Item>({
      ...item,
      name: item.name ?? "",
      windows: item.windows ?? [],
      blocked_dates: item.blocked_dates ?? [],
    }),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [baseVersion] = useState(version),
    [restricted, setRestricted] = useState(Boolean(item.windows?.length)),
    [blockedText, setBlockedText] = useState<string>(
      (item.blocked_dates ?? []).join(", "),
    );
  const patch = (field: string, value: any) =>
    setForm((f) => ({ ...f, [field]: value }));
  const optionalNumber = (field: string, label: string) => (
    <Field label={label}>
      <input
        type="number"
        min="1"
        value={form[field] ?? ""}
        onChange={(e) =>
          patch(field, e.target.value ? Number(e.target.value) : null)
        }
      />
    </Field>
  );
  return (
    <Modal
      title={`${item.id ? "Редактирование" : "Добавление"}: ${catalogs[kind].toLowerCase()}`}
      onClose={onClose}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          setBusy(true);
          try {
            const outgoing = { ...form };
            if (kind === "subjects") {
              delete outgoing.windows;
              delete outgoing.blocked_dates;
            } else {
              outgoing.blocked_dates = blockedText
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean);
              outgoing.windows = restricted ? form.windows : [];
              if (restricted && !outgoing.windows.length)
                throw new Error("Добавьте хотя бы один разрешённый интервал");
            }
            await save(`/catalog/${kind}/${item.id ?? uid()}`, {
              version: baseVersion,
              item: outgoing,
            });
            onClose();
          } catch (x) {
            setError((x as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="modal-body">
          <Field label={kind === "teachers" ? "ФИО преподавателя" : "Название"}>
            <input
              required
              autoFocus
              value={form.name}
              onChange={(e) => patch("name", e.target.value)}
            />
          </Field>
          {kind === "subjects" && (
            <Field label="Код дисциплины / МДК">
              <input
                value={form.code ?? ""}
                onChange={(e) => patch("code", e.target.value)}
              />
            </Field>
          )}
          {kind === "groups" && (
            <>
              <div className="form-grid">
                <Field label="Программа / специальность">
                  <input
                    value={form.program ?? ""}
                    onChange={(e) => patch("program", e.target.value)}
                  />
                </Field>
                <Field label="Поток">
                  <input
                    value={form.stream ?? ""}
                    onChange={(e) => patch("stream", e.target.value)}
                  />
                </Field>
                <Field label="Курс">
                  <input
                    type="number"
                    min="1"
                    max="6"
                    value={form.course ?? 1}
                    onChange={(e) => patch("course", Number(e.target.value))}
                  />
                </Field>
                <Field label="База обучения">
                  <select
                    value={form.base ?? "9"}
                    onChange={(e) => patch("base", e.target.value)}
                  >
                    <option>9</option>
                    <option>11</option>
                  </select>
                </Field>
                {optionalNumber("student_count", "Количество студентов")}
                <Field label="Год набора">
                  <input
                    type="number"
                    min="2000"
                    max="2100"
                    value={form.entry_year ?? ""}
                    onChange={(e) =>
                      patch(
                        "entry_year",
                        e.target.value ? Number(e.target.value) : null,
                      )
                    }
                  />
                </Field>
              </div>
              <Field label="Родительская группа (для подгруппы)">
                <Pick
                  items={Object.values(state.groups).filter(
                    (g) => g.id !== item.id,
                  )}
                  value={form.parent_id ?? ""}
                  onChange={(v) => patch("parent_id", v || null)}
                  empty="Самостоятельная группа"
                />
              </Field>
            </>
          )}
          {kind === "rooms" && (
            <div className="form-grid">
              <Field label="Корпус / адрес">
                <input
                  value={form.building ?? ""}
                  onChange={(e) => patch("building", e.target.value)}
                />
              </Field>
              <Field label="Тип">
                <select
                  value={form.kind ?? "classroom"}
                  onChange={(e) => patch("kind", e.target.value)}
                >
                  <option value="classroom">Аудитория</option>
                  <option value="lab">Лаборатория</option>
                  <option value="gym">Спортзал</option>
                  <option value="clinic">Клиническая база</option>
                </select>
              </Field>
              <Field
                label="Одновременных занятий"
                hint="Для отдельного кабинета обычно 1. Для базы укажите подтверждённый лимит."
              >
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={form.parallel_capacity ?? 1}
                  onChange={(e) =>
                    patch("parallel_capacity", Number(e.target.value))
                  }
                />
              </Field>
              {optionalNumber("student_capacity", "Вместимость, студентов")}
            </div>
          )}
          {["teachers", "groups"].includes(kind) && (
            <div className="form-grid">
              {optionalNumber("max_day_hours", "Предел часов в день")}
              {optionalNumber("max_week_hours", "Предел часов в неделю")}
            </div>
          )}
          {kind !== "subjects" && (
            <>
              <div className="section-divider" />
              <h3>Доступность</h3>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={restricted}
                  onChange={(e) => setRestricted(e.target.checked)}
                />
                Ограничить доступные часы
              </label>
              {restricted && (
                <>
                  <small>
                    Указанные интервалы разрешены. Остальное время недоступно.
                    Интервал на конкретную дату заменяет недельный режим этого
                    дня.
                  </small>
                  {form.windows.map((w: Item, i: number) => (
                    <div className="window-row" key={i}>
                      <select
                        value={w.weekday}
                        onChange={(e) =>
                          patch(
                            "windows",
                            form.windows.map((x: Item, j: number) =>
                              j === i
                                ? { ...x, weekday: Number(e.target.value) }
                                : x,
                            ),
                          )
                        }
                      >
                        {days.map((d, j) => (
                          <option value={j} key={d}>
                            {d}
                          </option>
                        ))}
                      </select>
                      <input
                        type="time"
                        value={clock(w.start)}
                        onChange={(e) =>
                          patch(
                            "windows",
                            form.windows.map((x: Item, j: number) =>
                              j === i
                                ? { ...x, start: minutes(e.target.value) }
                                : x,
                            ),
                          )
                        }
                      />
                      <input
                        type="time"
                        value={clock(w.end)}
                        onChange={(e) =>
                          patch(
                            "windows",
                            form.windows.map((x: Item, j: number) =>
                              j === i
                                ? { ...x, end: minutes(e.target.value) }
                                : x,
                            ),
                          )
                        }
                      />
                      <input
                        type="date"
                        aria-label="Дата исключения"
                        value={w.day ?? ""}
                        onChange={(e) =>
                          patch(
                            "windows",
                            form.windows.map((x: Item, j: number) =>
                              j === i
                                ? { ...x, day: e.target.value || null }
                                : x,
                            ),
                          )
                        }
                      />
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() =>
                          patch(
                            "windows",
                            form.windows.filter(
                              (_: Item, j: number) => j !== i,
                            ),
                          )
                        }
                      >
                        <X size={15} />
                      </button>
                    </div>
                  ))}
                  <Button
                    type="button"
                    onClick={() =>
                      patch("windows", [
                        ...form.windows,
                        { weekday: 0, start: 510, end: 1020, day: null },
                      ])
                    }
                  >
                    <Plus size={14} />
                    Интервал
                  </Button>
                </>
              )}
              <Field
                label="Полностью недоступные даты"
                hint="Перечислите через запятую в формате ГГГГ-ММ-ДД."
              >
                <input
                  value={blockedText}
                  onChange={(e) => setBlockedText(e.target.value)}
                />
              </Field>
            </>
          )}
          {error && <Notice error>{error}</Notice>}
        </div>
        <div className="modal-footer">
          <Button type="button" onClick={onClose}>
            Отмена
          </Button>
          <Button className="primary" disabled={busy}>
            {busy ? "Сохраняем…" : "Сохранить"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function Load({
  state,
  version,
  week,
  setWeek,
  save,
  editor,
}: Common & { week: string; setWeek: (v: string) => void }) {
  const [item, setItem] = useState<Item | null>(null);
  const items = Object.values(state.requirements).filter(
    (r) => r.week === week,
  );
  return (
    <div className="panel">
      <div className="toolbar">
        <WeekControl week={week} onChange={setWeek} />
        <Button
          className="primary"
          onClick={() => {
            setItem({});
            editor(true);
          }}
        >
          <Plus size={16} />
          Нагрузка
        </Button>
      </div>
      <div className="panel-note">
        Часы задаются в академических часах. Общее занятие потока оформляется
        одной строкой, практика разных групп отдельными строками.
      </div>
      {!items.length ? (
        <div className="empty">
          <Layers3 size={36} />
          <h3>На эту неделю нет нагрузки</h3>
          <p>Загрузите КУГ или добавьте подтверждённые часы вручную.</p>
        </div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Дисциплина / группы</th>
              <th>Вид</th>
              <th>Преподаватели</th>
              <th>Часы</th>
              <th>Блок</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id}>
                <td>
                  <b>{state.subjects[r.subject_id]?.name}</b>
                  <small>{names(state.groups, r.group_ids)}</small>
                </td>
                <td>
                  <span className={`badge ${r.kind}`}>{labels[r.kind]}</span>
                </td>
                <td>{names(state.teachers, r.teacher_ids)}</td>
                <td>{r.hours}</td>
                <td>{r.block_hours} ч.</td>
                <td className="table-actions">
                  <button
                    className="icon-button"
                    onClick={() => {
                      setItem(r);
                      editor(true);
                    }}
                    aria-label="Редактировать нагрузку"
                  >
                    <Pencil size={16} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label="Удалить нагрузку"
                    onClick={async () => {
                      if (
                        window.confirm(
                          "Удалить нагрузку? Сначала нужно удалить связанные занятия.",
                        )
                      )
                        try {
                          await save(
                            `/requirements/${r.id}?version=${version}`,
                            undefined,
                            "DELETE",
                          );
                        } catch {}
                    }}
                  >
                    <Trash2 size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {item && (
        <RequirementEditor
          state={state}
          version={version}
          item={item}
          week={week}
          save={save}
          onClose={() => {
            setItem(null);
            editor(false);
          }}
        />
      )}
    </div>
  );
}

function RequirementEditor({
  state,
  version,
  item,
  week,
  save,
  onClose,
}: {
  state: College;
  version: number;
  item: Item;
  week: string;
  save: Save;
  onClose: () => void;
}) {
  const [form, setForm] = useState<Item>({
      subject_id: "",
      group_ids: [],
      teacher_ids: [],
      room_ids: [],
      week,
      kind: "theory",
      hours: 2,
      block_hours: 2,
      ...item,
    }),
    [baseVersion] = useState(version),
    [error, setError] = useState("");
  const patch = (key: string, v: any) => setForm((f) => ({ ...f, [key]: v }));
  return (
    <Modal
      title={item.id ? "Редактирование нагрузки" : "Новая нагрузка"}
      onClose={onClose}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await save(`/requirements/${item.id ?? uid()}`, {
              version: baseVersion,
              item: form,
            });
            onClose();
          } catch (x) {
            setError((x as Error).message);
          }
        }}
      >
        <div className="modal-body">
          <Field label="Дисциплина">
            <Pick
              items={Object.values(state.subjects)}
              value={form.subject_id}
              onChange={(v) => patch("subject_id", v)}
            />
          </Field>
          <div className="form-grid">
            <Field label="Неделя: понедельник">
              <input
                type="date"
                value={form.week}
                onChange={(e) => patch("week", e.target.value)}
                required
              />
            </Field>
            <Field label="Вид занятия">
              <select
                value={form.kind}
                onChange={(e) => patch("kind", e.target.value)}
              >
                {Object.entries(labels).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Всего академических часов">
              <input
                type="number"
                min="1"
                value={form.hours}
                onChange={(e) => patch("hours", Number(e.target.value))}
              />
            </Field>
            <Field label="Часов в непрерывном блоке">
              <input
                type="number"
                min="1"
                max="24"
                value={form.block_hours}
                onChange={(e) => patch("block_hours", Number(e.target.value))}
              />
            </Field>
          </div>
          <Field label="Участники общего занятия">
            <Multi
              items={Object.values(state.groups)}
              value={form.group_ids}
              onChange={(v) => patch("group_ids", v)}
            />
          </Field>
          <Field
            label="Разрешённые преподаватели"
            hint="Генератор выбирает одного из списка. Для совместного преподавания укажите участников при ручной правке."
          >
            <Multi
              items={Object.values(state.teachers)}
              value={form.teacher_ids}
              onChange={(v) => patch("teacher_ids", v)}
            />
          </Field>
          <Field label="Разрешённые помещения">
            <Multi
              items={Object.values(state.rooms)}
              value={form.room_ids}
              onChange={(v) => patch("room_ids", v)}
            />
          </Field>
          {item.source_ref && (
            <small>
              Часы связаны с импортированным документом. Изменения фиксируются в
              истории.
            </small>
          )}
          {error && <Notice error>{error}</Notice>}
        </div>
        <div className="modal-footer">
          <Button type="button" onClick={onClose}>
            Отмена
          </Button>
          <Button className="primary">Сохранить</Button>
        </div>
      </form>
    </Modal>
  );
}

function LessonEditor({
  state,
  version,
  item,
  week,
  save,
  onClose,
}: {
  state: College;
  version: number;
  item: Item;
  week: string;
  save: Save;
  onClose: () => void;
}) {
  const [form, setForm] = useState<Item>({
      requirement_id: null,
      subject_id: "",
      group_ids: [],
      teacher_ids: [],
      room_id: "",
      day: week,
      start: state.settings.bells[0].start,
      end: state.settings.bells[0].end,
      hours: state.settings.bells[0].hours,
      kind: "theory",
      locked: false,
      note: "",
      ...item,
    }),
    [baseVersion] = useState(version),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const patch = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }));
  const needs = Object.values(state.requirements)
    .filter((r) => r.week <= form.day && form.day < shift(r.week, 7))
    .map((r) => ({
      ...r,
      name: `${state.subjects[r.subject_id]?.name} · ${names(state.groups, r.group_ids)} · ${labels[r.kind]}`,
    }));
  return (
    <Modal
      title={item.id ? "Редактирование занятия" : "Новое занятие"}
      onClose={onClose}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await save(`/lessons/${item.id ?? uid()}`, {
              version: baseVersion,
              item: form,
            });
            onClose();
          } catch (x) {
            setError((x as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="modal-body">
          <Field label="Связь с нагрузкой">
            <Pick
              items={needs}
              value={form.requirement_id ?? ""}
              empty="Вне плановой нагрузки"
              onChange={(v) => {
                const r = state.requirements[v];
                setForm((f) =>
                  r
                    ? {
                        ...f,
                        requirement_id: v,
                        subject_id: r.subject_id,
                        group_ids: r.group_ids,
                        teacher_ids: [r.teacher_ids[0]],
                        room_id: r.room_ids[0],
                        kind: r.kind,
                      }
                    : { ...f, requirement_id: null },
                );
              }}
            />
          </Field>
          <Field label="Дисциплина">
            <Pick
              items={Object.values(state.subjects)}
              disabled={Boolean(form.requirement_id)}
              value={form.subject_id}
              onChange={(v) => patch("subject_id", v)}
            />
          </Field>
          <div className="form-grid">
            <Field label="Дата">
              <input
                type="date"
                required
                value={form.day}
                onChange={(e) => patch("day", e.target.value)}
              />
            </Field>
            <Field label="Вид занятия">
              <select
                disabled={Boolean(form.requirement_id)}
                value={form.kind}
                onChange={(e) => patch("kind", e.target.value)}
              >
                {Object.entries(labels).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Начало">
              <input
                type="time"
                required
                value={clock(form.start)}
                onChange={(e) => patch("start", minutes(e.target.value))}
              />
            </Field>
            <Field label="Окончание">
              <input
                type="time"
                required
                value={clock(form.end)}
                onChange={(e) => patch("end", minutes(e.target.value))}
              />
            </Field>
            <Field label="Академических часов">
              <input
                type="number"
                min="1"
                max="24"
                value={form.hours}
                onChange={(e) => patch("hours", Number(e.target.value))}
              />
            </Field>
            <Field label="Помещение">
              <Pick
                items={Object.values(state.rooms).filter(
                  (r) =>
                    !form.requirement_id ||
                    state.requirements[form.requirement_id].room_ids.includes(
                      r.id,
                    ),
                )}
                value={form.room_id}
                onChange={(v) => patch("room_id", v)}
              />
            </Field>
          </div>
          <Field label="Группы">
            {form.requirement_id ? (
              <div className="readonly">
                {names(state.groups, form.group_ids)}
              </div>
            ) : (
              <Multi
                items={Object.values(state.groups)}
                value={form.group_ids}
                onChange={(v) => patch("group_ids", v)}
              />
            )}
          </Field>
          <Field label="Преподаватели">
            <Multi
              items={Object.values(state.teachers).filter(
                (t) =>
                  !form.requirement_id ||
                  state.requirements[form.requirement_id].teacher_ids.includes(
                    t.id,
                  ),
              )}
              value={form.teacher_ids}
              onChange={(v) => patch("teacher_ids", v)}
            />
          </Field>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.locked}
              onChange={(e) => patch("locked", e.target.checked)}
            />
            <LockKeyhole size={15} />
            Закрепить при повторной генерации
          </label>
          <Field label="Комментарий">
            <textarea
              value={form.note}
              onChange={(e) => patch("note", e.target.value)}
            />
          </Field>
          {error && <Notice error>{error}</Notice>}
        </div>
        <div className="modal-footer">
          {item.id && (
            <Button
              type="button"
              className="danger"
              onClick={async () => {
                if (window.confirm("Удалить занятие?"))
                  try {
                    await save(
                      `/lessons/${item.id}?version=${baseVersion}`,
                      undefined,
                      "DELETE",
                    );
                    onClose();
                  } catch (x) {
                    setError((x as Error).message);
                  }
              }}
            >
              <Trash2 size={15} />
              Удалить
            </Button>
          )}
          <span className="spacer" />
          <Button type="button" onClick={onClose}>
            Отмена
          </Button>
          <Button className="primary" disabled={busy}>
            Сохранить
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function Swap({
  state,
  version,
  save,
  week,
  onClose,
}: {
  state: College;
  version: number;
  save: Save;
  week: string;
  onClose: () => void;
}) {
  const [first, setFirst] = useState(""),
    [second, setSecond] = useState(""),
    [error, setError] = useState(""),
    [baseVersion] = useState(version);
  const options: Item[] = Object.values(state.lessons)
    .filter((l) => l.day >= week && l.day < shift(week, 7))
    .map((l) => ({
      ...l,
      name: `${l.day} ${clock(l.start)} · ${state.subjects[l.subject_id]?.name} · ${names(state.groups, l.group_ids)}`,
    }));
  return (
    <Modal title="Обменять занятия местами" onClose={onClose}>
      <div className="modal-body">
        <p>
          Дата и время двух занятий поменяются одной правкой. Преподаватели,
          группы, помещения и часы сохранятся.
        </p>
        <Field label="Первое занятие">
          <Pick items={options} value={first} onChange={setFirst} />
        </Field>
        <Field label="Второе занятие">
          <Pick
            items={options.filter((l) => l.id !== first)}
            value={second}
            onChange={setSecond}
          />
        </Field>
        {error && <Notice error>{error}</Notice>}
      </div>
      <div className="modal-footer">
        <Button onClick={onClose}>Отмена</Button>
        <Button
          className="primary"
          onClick={async () => {
            try {
              await save(
                "/lessons/swap",
                { version: baseVersion, item: { first, second } },
                "POST",
              );
              onClose();
            } catch (x) {
              setError((x as Error).message);
            }
          }}
        >
          Обменять
        </Button>
      </div>
    </Modal>
  );
}

function Generator({
  state,
  version,
  week,
  api,
  save,
  onClose,
}: {
  state: College;
  version: number;
  week: string;
  api: Api;
  save: Save;
  onClose: () => void;
}) {
  const [groups, setGroups] = useState<string[]>([]),
    [job, setJob] = useState<Item | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!job?.id || !["queued", "running"].includes(job.status)) return;
    const timer = setInterval(
      () =>
        api("/generations/" + job.id)
          .then(setJob)
          .catch((e) => setError(e.message)),
      1500,
    );
    return () => clearInterval(timer);
  }, [job?.id, job?.status, api]);
  const result = job?.result;
  return (
    <Modal title="Сформировать расписание" wide onClose={onClose}>
      <div className="modal-body">
        <div className="generation-heading">
          <span className="big-icon">
            <Sparkles />
          </span>
          <div>
            <h3>Неделя {dateLabel(week)}</h3>
            <p>
              Закреплённые занятия останутся на своих местах. Проверка ресурсов
              учитывает другие группы и курсы.
            </p>
          </div>
        </div>
        {!job && (
          <>
            <Field
              label="Группы для расчёта"
              hint="Ничего не выбрано: весь колледж. Для общего занятия выбирайте все входящие группы."
            >
              <Multi
                items={Object.values(state.groups)}
                value={groups}
                onChange={setGroups}
              />
            </Field>
            {!state.settings.confirmed && (
              <Notice>
                Сначала подтвердите учебные дни и звонки в настройках.
              </Notice>
            )}
          </>
        )}
        {job && ["queued", "running"].includes(job.status) && (
          <div className="working">
            <RefreshCw className="spin" size={24} />
            <h3>
              {job.status === "queued"
                ? "Расчёт в очереди"
                : "Подбираем допустимое расписание"}
            </h3>
            <p>Существующее расписание остаётся доступным.</p>
          </div>
        )}
        {result && (
          <>
            <Notice error={!["optimal", "feasible"].includes(result.status)}>
              {result.message}
            </Notice>
            {result.lessons?.length > 0 && (
              <div className="candidate-table">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Дата / время</th>
                      <th>Занятие</th>
                      <th>Преподаватель</th>
                      <th>Помещение</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...result.lessons]
                      .sort(
                        (a, b) =>
                          a.day.localeCompare(b.day) || a.start - b.start,
                      )
                      .map((l: Item) => (
                        <tr key={l.id}>
                          <td>
                            {dateLabel(l.day)}
                            <small>
                              {clock(l.start)}–{clock(l.end)} · {l.hours} ч.
                            </small>
                          </td>
                          <td>
                            {state.subjects[l.subject_id]?.name}
                            <small>{names(state.groups, l.group_ids)}</small>
                          </td>
                          <td>{names(state.teachers, l.teacher_ids)}</td>
                          <td>{state.rooms[l.room_id]?.name}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
            {job.source_version !== version && (
              <Notice>
                Данные изменились после начала расчёта. Сформируйте новый
                вариант перед применением.
              </Notice>
            )}
          </>
        )}
        {error && <Notice error>{error}</Notice>}
      </div>
      <div className="modal-footer">
        <Button onClick={onClose}>Закрыть</Button>
        {!job && (
          <Button
            className="primary"
            disabled={busy || !state.settings.confirmed}
            onClick={async () => {
              setBusy(true);
              try {
                setJob(
                  await api("/generations", {
                    method: "POST",
                    body: JSON.stringify({
                      version,
                      item: { week, group_ids: groups },
                    }),
                  }),
                );
              } catch (x) {
                setError((x as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Sparkles size={15} />
            Запустить расчёт
          </Button>
        )}
        {result && ["optimal", "feasible"].includes(result.status) && (
          <Button
            className="primary"
            disabled={busy || job?.source_version !== version}
            onClick={async () => {
              setBusy(true);
              try {
                await save(
                  `/generations/${job?.id}/apply`,
                  { version },
                  "POST",
                );
                onClose();
              } catch (x) {
                setError((x as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Применить вариант
          </Button>
        )}
        {result && (
          <Button
            onClick={() => {
              setJob(null);
              setError("");
            }}
          >
            Новый расчёт
          </Button>
        )}
      </div>
    </Modal>
  );
}

function CalendarSettings({ state, version, save, editor }: Common) {
  const [form, setForm] = useState<Item>(state.settings),
    [baseVersion, setBaseVersion] = useState(version),
    [dirty, setDirty] = useState(false),
    [error, setError] = useState(""),
    [holidaysText, setHolidaysText] = useState<string>(
      state.settings.holidays.join(", "),
    );
  useEffect(() => {
    if (!dirty) {
      setForm(state.settings);
      setHolidaysText(state.settings.holidays.join(", "));
      setBaseVersion(version);
    }
  }, [state.settings, version, dirty]);
  useEffect(() => () => editor(false), []);
  const patch = (k: string, v: any) => {
    setForm((f) => ({ ...f, [k]: v }));
    setDirty(true);
    editor(true);
  };
  return (
    <form
      className="settings-layout"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await save("/settings", {
            version: baseVersion,
            item: {
              ...form,
              holidays: holidaysText
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean),
            },
          });
          setDirty(false);
          editor(false);
        } catch (x) {
          setError((x as Error).message);
        }
      }}
    >
      <div className="panel settings-main">
        <div className="panel-title">
          <CalendarDays size={19} />
          <h3>Учебный календарь</h3>
        </div>
        <div className="panel-body">
          <Field label="Название рабочего пространства">
            <input
              value={form.name}
              onChange={(e) => patch("name", e.target.value)}
            />
          </Field>
          <Field label="Учебные дни">
            <div className="weekday-pills">
              {days.map((d, i) => (
                <label
                  className={form.study_days.includes(i) ? "active" : ""}
                  key={d}
                >
                  <input
                    type="checkbox"
                    checked={form.study_days.includes(i)}
                    onChange={(e) =>
                      patch(
                        "study_days",
                        e.target.checked
                          ? [...form.study_days, i].sort()
                          : form.study_days.filter((x: number) => x !== i),
                      )
                    }
                  />
                  {d.slice(0, 2)}
                </label>
              ))}
            </div>
          </Field>
          <div className="form-grid">
            <Field label="Минут в академическом часе">
              <input
                type="number"
                min="20"
                max="90"
                value={form.academic_minutes}
                onChange={(e) =>
                  patch("academic_minutes", Number(e.target.value))
                }
              />
            </Field>
            <Field label="Переход между корпусами, минут">
              <input
                type="number"
                min="0"
                max="180"
                value={form.transition_minutes}
                onChange={(e) =>
                  patch("transition_minutes", Number(e.target.value))
                }
              />
            </Field>
          </div>
          <Field
            label="Неучебные даты"
            hint="Даты через запятую: ГГГГ-ММ-ДД. Учебные и производственные практики задавайте в нагрузке отдельно."
          >
            <textarea
              value={holidaysText}
              onChange={(e) => {
                setHolidaysText(e.target.value);
                setDirty(true);
                editor(true);
              }}
            />
          </Field>
          <div className="section-divider" />
          <h3>Расписание звонков</h3>
          <div className="bell-labels">
            <span>Пара</span>
            <span>Начало</span>
            <span>Окончание</span>
            <span>Акад. ч.</span>
          </div>
          {form.bells.map((b: Item, i: number) => (
            <div className="bell-row" key={i}>
              {["number", "start", "end", "hours"].map((key) => (
                <input
                  key={key}
                  aria-label={`${key} пары ${i + 1}`}
                  type={["start", "end"].includes(key) ? "time" : "number"}
                  min="1"
                  value={
                    ["start", "end"].includes(key) ? clock(b[key]) : b[key]
                  }
                  onChange={(e) =>
                    patch(
                      "bells",
                      form.bells.map((x: Item, j: number) =>
                        j === i
                          ? {
                              ...x,
                              [key]: ["start", "end"].includes(key)
                                ? minutes(e.target.value)
                                : Number(e.target.value),
                            }
                          : x,
                      ),
                    )
                  }
                />
              ))}
              <button
                type="button"
                className="icon-button"
                onClick={() =>
                  patch(
                    "bells",
                    form.bells.filter((_: Item, j: number) => j !== i),
                  )
                }
              >
                <X size={16} />
              </button>
            </div>
          ))}
          <Button
            type="button"
            onClick={() => {
              const last = form.bells.at(-1);
              patch("bells", [
                ...form.bells,
                {
                  number: (last?.number ?? 0) + 1,
                  start: (last?.end ?? 500) + 10,
                  end: (last?.end ?? 500) + 100,
                  hours: 2,
                },
              ]);
            }}
          >
            <Plus size={15} />
            Добавить пару
          </Button>
          <div className="section-divider" />
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.confirmed}
              onChange={(e) => patch("confirmed", e.target.checked)}
            />
            Учебные дни, продолжительность и звонки проверены
          </label>
          {error && <Notice error>{error}</Notice>}
          <Button className="primary settings-save" disabled={!dirty}>
            Сохранить настройки
          </Button>
        </div>
      </div>
      <aside className="panel settings-help">
        <ShieldCheck size={27} />
        <h3>Сначала подтвердите правила</h3>
        <p>
          Начальные звонки являются примером. Автоматическое составление
          доступно после проверки календаря.
        </p>
        <p>
          Предельные часы и доступность отдельных преподавателей, групп и
          помещений задаются в справочниках.
        </p>
        <p>
          Даты недель из КУГ подтверждаются при импорте. Приложение не меняет
          календарь по текстовым заголовкам файла.
        </p>
      </aside>
    </form>
  );
}

function Imports({
  state,
  version,
  api,
  save,
  week,
  editor,
}: Common & { api: Api; week: string }) {
  const [kind, setKind] = useState("kug"),
    [documents, setDocuments] = useState<Item[]>([]),
    [document, setDocument] = useState<Item | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const reload = () => api("/imports").then(setDocuments);
  useEffect(() => {
    reload();
  }, []);
  const close = () => {
    setDocument(null);
    editor(false);
  };
  return (
    <>
      <div className="import-intro">
        <div>
          <h2>Из Excel в рабочее расписание</h2>
          <p>
            Сначала проверьте распознанные данные. Подтверждённые строки станут
            учебной нагрузкой.
          </p>
        </div>
        <a className="button" href="/api/templates/load.xlsx">
          <Download size={16} />
          Шаблон нагрузки
        </a>
      </div>
      <div className="panel upload-panel">
        <div className="tabs">
          <button
            className={kind === "kug" ? "active" : ""}
            onClick={() => setKind("kug")}
          >
            Календарный учебный график
          </button>
          <button
            className={kind === "load" ? "active" : ""}
            onClick={() => setKind("load")}
          >
            Преподавательская нагрузка
          </button>
        </div>
        <label className="upload-zone">
          <FolderInput size={32} />
          <b>{busy ? "Читаем документ…" : "Выберите файл Excel"}</b>
          <span>XLSX, до 10 МБ · исходный документ сохраняется</span>
          <input
            type="file"
            accept=".xlsx"
            disabled={busy}
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              setBusy(true);
              setError("");
              const form = new FormData();
              form.append("file", file);
              try {
                const d = await api("/imports?kind=" + kind, {
                  method: "POST",
                  body: form,
                });
                setDocument(d);
                editor(true);
                await reload();
              } catch (x) {
                setError((x as Error).message);
              } finally {
                setBusy(false);
                e.target.value = "";
              }
            }}
          />
          <span className="button primary">Выбрать файл</span>
        </label>
        {error && <Notice error>{error}</Notice>}
      </div>
      <div className="panel">
        <div className="panel-title">
          <History size={18} />
          <h3>Загруженные документы</h3>
        </div>
        {!documents.length ? (
          <div className="empty compact">Документы ещё не загружены.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Документ</th>
                <th>Тип</th>
                <th>Загружен</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => (
                <tr key={d.id}>
                  <td>
                    <b>{d.filename}</b>
                  </td>
                  <td>{d.kind === "kug" ? "КУГ" : "Нагрузка"}</td>
                  <td>{new Date(d.at).toLocaleDateString("ru")}</td>
                  <td>
                    <Button
                      onClick={async () => {
                        setDocument(await api("/imports/" + d.id));
                        editor(true);
                      }}
                    >
                      Проверить
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {document &&
        (document.preview.format === "kug" ? (
          <KugImport
            state={state}
            version={version}
            document={document}
            save={save}
            week={week}
            onClose={close}
          />
        ) : (
          <LoadImport
            version={version}
            document={document}
            save={save}
            week={week}
            onClose={close}
          />
        ))}
    </>
  );
}

function KugImport({
  state,
  version,
  document,
  save,
  week,
  onClose,
}: {
  state: College;
  version: number;
  document: Item;
  save: Save;
  week: string;
  onClose: () => void;
}) {
  const p = document.preview,
    [sheetKey, setSheet] = useState(p.sheets[0]?.key ?? ""),
    [weekKey, setWeekKey] = useState(p.sheets[0]?.weeks[0]?.key ?? ""),
    [targetWeek, setTargetWeek] = useState(week),
    [groups, setGroups] = useState<string[]>([]),
    [ack, setAck] = useState(false),
    [mapping, setMapping] = useState<Record<string, Item>>({}),
    [baseVersion] = useState(version),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const sheet = p.sheets.find((s: Item) => s.key === sheetKey),
    rows = sheet?.rows.filter((r: Item) => r.hours[weekKey] > 0) ?? [];
  const setRow = (key: string, field: string, value: any) =>
    setMapping((m) => ({ ...m, [key]: { ...m[key], [field]: value } }));
  return (
    <Modal title="Проверка КУГ" wide onClose={onClose}>
      <div className="modal-body">
        <p className="document-name">{p.filename}</p>
        <div className="form-grid">
          <Field label="Лист / курс">
            <select
              value={sheetKey}
              onChange={(e) => {
                setSheet(e.target.value);
                const s = p.sheets.find((x: Item) => x.key === e.target.value);
                setWeekKey(s?.weeks[0]?.key ?? "");
                setAck(false);
                setMapping({});
              }}
            >
              {p.sheets.map((s: Item) => (
                <option key={s.key} value={s.key}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Столбец недели в исходнике">
            <select
              value={weekKey}
              onChange={(e) => {
                setWeekKey(e.target.value);
                setAck(false);
              }}
            >
              {sheet?.weeks.map((w: Item) => (
                <option key={w.key} value={w.key}>
                  {w.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Реальная учебная неделя: понедельник">
            <input
              type="date"
              value={targetWeek}
              onChange={(e) => {
                setTargetWeek(e.target.value);
                setAck(false);
              }}
            />
          </Field>
          <Field label="Часов по исходным строкам">
            <div className="readonly">
              {rows.reduce((n: number, r: Item) => n + r.hours[weekKey], 0)}{" "}
              академических часов
            </div>
          </Field>
        </div>
        <details className="source-details">
          <summary>Заголовки исходного листа</summary>
          {sheet?.metadata.map((m: string, i: number) => (
            <p key={i}>{m}</p>
          ))}
        </details>
        {sheet?.errors
          ?.filter((e: Item) => e.week_key === weekKey)
          .map((e: Item, i: number) => (
            <Notice key={"error" + i} error>
              {e.cell}: {e.message}
            </Notice>
          ))}
        {sheet?.warnings.map((w: string, i: number) => (
          <Notice key={i}>{w}</Notice>
        ))}
        <Field label="Учебные группы этого КУГ">
          <Multi
            items={Object.values(state.groups)}
            value={groups}
            onChange={(v) => {
              setGroups(v);
              setAck(false);
            }}
          />
        </Field>
        <h3>Сопоставление занятий</h3>
        <p className="muted">
          Укажите преподавателя и помещение для каждой строки. Теория выбранных
          групп станет общим занятием; практика отдельной нагрузкой каждой
          группы.
        </p>
        {!rows.length && (
          <Notice>В этом столбце нет часов. Выберите другую неделю.</Notice>
        )}
        <div className="import-table-wrap">
          <table className="data-table import-table">
            <thead>
              <tr>
                <th>Дисциплина / часы</th>
                <th>Вид</th>
                <th>Преподаватель</th>
                <th>Помещение</th>
                <th>Блок, ч.</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r: Item) => {
                if (r.kind === "self_study")
                  return (
                    <tr key={r.key}>
                      <td>
                        {r.code} · {r.name}
                        <small>{r.hours[weekKey]} ч.</small>
                      </td>
                      <td colSpan={4}>
                        <span className="badge">Самостоятельная работа</span>
                        <small>Сохраняется в плане, без назначения пар</small>
                      </td>
                    </tr>
                  );
                const m = mapping[r.key] ?? {};
                return (
                  <tr key={r.key}>
                    <td>
                      <b>{r.name}</b>
                      <small>
                        {r.code} · {r.hours[weekKey]} ч. ·{" "}
                        {r.refs[weekKey].join(", ")}
                      </small>
                      <Pick
                        items={Object.values(state.subjects)}
                        empty="Создать дисциплину по КУГ"
                        value={m.subject_id ?? ""}
                        onChange={(v) => setRow(r.key, "subject_id", v)}
                      />
                    </td>
                    <td>
                      <select
                        value={m.kind ?? (r.kind === "unknown" ? "" : r.kind)}
                        onChange={(e) => setRow(r.key, "kind", e.target.value)}
                      >
                        <option value="">Укажите вид</option>
                        {Object.entries(labels).map(([v, l]) => (
                          <option key={v} value={v}>
                            {l}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <Pick
                        items={Object.values(state.teachers)}
                        value={m.teacher ?? ""}
                        onChange={(v) => setRow(r.key, "teacher", v)}
                      />
                    </td>
                    <td>
                      <Pick
                        items={Object.values(state.rooms)}
                        value={m.room ?? ""}
                        onChange={(v) => setRow(r.key, "room", v)}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        min="1"
                        max="24"
                        value={m.block_hours ?? 2}
                        onChange={(e) =>
                          setRow(r.key, "block_hours", Number(e.target.value))
                        }
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <label className="checkbox acknowledgment">
          <input
            type="checkbox"
            checked={ack}
            onChange={(e) => setAck(e.target.checked)}
          />
          Я проверил курс, базу обучения, набор и привязку столбца КУГ к
          выбранным группам и календарной неделе.
        </label>
        {error && <Notice error>{error}</Notice>}
      </div>
      <div className="modal-footer">
        <a
          className="text-button"
          href={`/api/imports/${document.id}/original`}
        >
          Исходный Excel
        </a>
        <span className="spacer" />
        <Button onClick={onClose}>Отмена</Button>
        <Button
          className="primary"
          disabled={
            busy ||
            !ack ||
            !groups.length ||
            !rows.length ||
            sheet?.errors?.some((e: Item) => e.week_key === weekKey)
          }
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              const selected = rows
                .filter((r: Item) => r.kind !== "self_study")
                .map((r: Item) => {
                  const m = mapping[r.key] ?? {};
                  if (!m.teacher || !m.room)
                    throw new Error(
                      "Сопоставьте преподавателя и помещение каждой строки",
                    );
                  return {
                    row_key: r.key,
                    subject_id: m.subject_id || null,
                    kind: m.kind ?? r.kind,
                    teacher_ids: [m.teacher],
                    room_ids: [m.room],
                    block_hours: m.block_hours ?? 2,
                  };
                });
              await save(
                `/imports/${document.id}/kug`,
                {
                  version: baseVersion,
                  item: {
                    sheet_key: sheetKey,
                    week_key: weekKey,
                    week: targetWeek,
                    group_ids: groups,
                    rows: selected,
                    acknowledged: ack,
                  },
                },
                "POST",
              );
              onClose();
            } catch (x) {
              setError((x as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Подтвердить нагрузку
        </Button>
      </div>
    </Modal>
  );
}

function LoadImport({
  version,
  document,
  save,
  week,
  onClose,
}: {
  version: number;
  document: Item;
  save: Save;
  week: string;
  onClose: () => void;
}) {
  const p = document.preview,
    [mapping, setMapping] = useState<Item>(p.mapping),
    [targetWeek, setWeek] = useState(week),
    [baseVersion] = useState(version),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const fields = {
    subject: "Предмет",
    group: "Группа",
    teacher: "Преподаватель",
    room: "Помещение",
    hours: "Часы",
    week: "Неделя",
    kind: "Вид занятия",
    block_hours: "Длительность блока",
  };
  return (
    <Modal title="Проверка преподавательской нагрузки" wide onClose={onClose}>
      <div className="modal-body">
        <p className="document-name">{p.filename}</p>
        <Notice>
          Названия должны совпадать со справочниками. Если на эту неделю уже
          загружен КУГ, часы сверяются, а назначения обновляются без
          дублирования.
        </Notice>
        <div className="form-grid">
          {Object.entries(fields).map(([key, label]) => (
            <Field label={label} key={key}>
              <select
                value={mapping[key] ?? ""}
                onChange={(e) =>
                  setMapping((m) => ({ ...m, [key]: e.target.value || null }))
                }
              >
                <option value="">Не задано</option>
                {p.headers.map((h: string, i: number) => (
                  <option value={i} key={i}>
                    {h || `Столбец ${i + 1}`}
                  </option>
                ))}
              </select>
            </Field>
          ))}
          <Field label="Неделя, если нет столбца дат">
            <input
              type="date"
              value={targetWeek}
              onChange={(e) => setWeek(e.target.value)}
            />
          </Field>
        </div>
        <h3>Первые строки · всего {p.rows.length}</h3>
        <div className="grid-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {p.headers.map((h: string, i: number) => (
                  <th key={i}>{h || `Столбец ${i + 1}`}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {p.rows.slice(0, 12).map((r: Item, i: number) => (
                <tr key={i}>
                  {p.headers.map((_: string, j: number) => (
                    <td key={j}>{String(r[j] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {error && <Notice error>{error}</Notice>}
      </div>
      <div className="modal-footer">
        <Button onClick={onClose}>Отмена</Button>
        <Button
          className="primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await save(
                `/imports/${document.id}/load`,
                { version: baseVersion, item: { mapping, week: targetWeek } },
                "POST",
              );
              onClose();
            } catch (x) {
              setError((x as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Импортировать {p.rows.length} строк
        </Button>
      </div>
    </Modal>
  );
}

function HistoryView({
  api,
  save,
  version,
}: {
  api: Api;
  save: Save;
  version: number;
}) {
  const [rows, setRows] = useState<Item[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    api("/history").then(setRows);
  }, [api, version]);
  return (
    <div className="panel">
      <div className="panel-title">
        <History size={19} />
        <h3>Сохранённые версии</h3>
      </div>
      <div className="panel-note">
        Восстановление возвращает все справочники, нагрузку и расписание к
        выбранной версии. Новая правка сохраняется в истории.
      </div>
      {error && <Notice error>{error}</Notice>}
      <table className="data-table">
        <thead>
          <tr>
            <th>Версия</th>
            <th>Изменение</th>
            <th>Составитель</th>
            <th>Время</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.version}>
              <td>
                <span className="version-tag">{r.version}</span>
                {r.version === version && <small>Текущая</small>}
              </td>
              <td>
                <b>{r.action}</b>
              </td>
              <td>{r.user_name}</td>
              <td>{new Date(r.at).toLocaleString("ru")}</td>
              <td>
                {r.version !== version && (
                  <Button
                    onClick={async () => {
                      if (
                        window.confirm(
                          `Вернуть все данные к версии ${r.version}? Текущее состояние останется в истории.`,
                        )
                      )
                        try {
                          await save(
                            `/history/${r.version}/restore`,
                            { version },
                            "POST",
                          );
                        } catch (x) {
                          setError((x as Error).message);
                        }
                    }}
                  >
                    Восстановить
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
