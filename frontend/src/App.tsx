import { useCallback, useEffect, useState } from "react";
import { AccessReviews } from "./AccessReviews";
import { Drive } from "./Drive";
import { OfficeEditor } from "./OfficeEditor";
import { Notifications } from "./Notifications";
import { Quotas } from "./Quotas";
import { Governance } from "./Governance";
import { AccessRequests } from "./AccessRequests";
import { ExternalShare } from "./Shares";
import { ResourceAdmin } from "./ResourceAdmin";
import { OrganizationAdmin } from "./OrganizationAdmin";
import { IdentityAdmin } from "./IdentityAdmin";
import { Icon } from "./Icons";
import { AdminDashboard } from "./AdminDashboard";

type UserProfile = {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  enabled: boolean;
};
type DriveView =
  | "mine"
  | "spaces"
  | "departments"
  | "shared"
  | "recent"
  | "favorites"
  | "trash";
type View =
  | DriveView
  | "requests"
  | "reviews"
  | "notifications"
  | "search"
  | "profile"
  | "administration";
const navigation: [View, string, string][] = [
  ["mine", "▤", "Мои документы"],
  ["spaces", "▣", "Общие пространства"],
  ["departments", "◫", "Отделы"],
  ["shared", "♧", "Доступные мне"],
  ["recent", "◷", "Недавние"],
  ["favorites", "☆", "Избранное"],
  ["requests", "↗", "Запросы доступа"],
  ["reviews", "✓", "Пересмотр доступа"],
  ["trash", "▥", "Корзина"],
  ["notifications", "●", "Уведомления"],
  ["search", "⌕", "Поиск"],
  ["profile", "○", "Профиль"],
];
export function App() {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>(() =>
    new URLSearchParams(window.location.search).has("document")
      ? "spaces"
      : "mine",
  );
  const [capabilities, setCapabilities] = useState({
    administration: false,
    organization: false,
  });
  const [searchHost, setSearchHost] = useState<HTMLDivElement | null>(null);
  const [adminTab, setAdminTab] = useState("overview");
  const loadMe = useCallback(async () => {
    try {
      const r = await fetch("/api/v1/auth/me");
      if (r.status === 401) {
        setUser(null);
        return;
      }
      if (!r.ok) throw new Error();
      setUser((await r.json()).data as UserProfile);
    } catch {
      setError("Не удалось проверить сеанс. Попробуйте обновить страницу.");
    } finally {
      setChecked(true);
    }
  }, []);
  useEffect(() => {
    void loadMe();
  }, [loadMe]);
  useEffect(() => {
    if (!user) return;
    let active = true;
    fetch("/api/v1/drive/capabilities")
      .then(async (r) => {
        if (!r.ok) throw new Error();
        const d = await r.json();
        if (active) setCapabilities(d.data as typeof capabilities);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [user]);
  async function logout() {
    try {
      const c = await fetch("/api/v1/auth/csrf");
      if (!c.ok) throw new Error();
      const r = await fetch("/api/v1/auth/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": (await c.json()).data.csrf_token as string },
      });
      if (!r.ok) throw new Error();
      setUser(null);
      setCapabilities({ administration: false, organization: false });
    } catch {
      setError("Не удалось завершить сеанс");
    }
  }
  if (window.location.pathname === "/share") return <ExternalShare />;
  if (!user)
    return (
      <main className="login-screen">
        <section className="card">
          <div className="brand">NambaDrive</div>
          <h1>Документы вашей команды</h1>
          <p>Храните, находите и редактируйте документы с контролем доступа.</p>
          <button
            disabled={!checked}
            onClick={() =>
              window.location.assign(
                "/api/v1/auth/login?next_url=" +
                  encodeURIComponent(
                    window.location.pathname + window.location.search,
                  ),
              )
            }
          >
            {checked ? "Войти через Authentik" : "Проверяем сеанс…"}
          </button>
          <p role="status">{error}</p>
        </section>
      </main>
    );
  const editorId = new URLSearchParams(window.location.search).get("editor");
  if (editorId) {
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(editorId)) {
      return <main><p role="alert">Некорректный адрес документа.</p></main>;
    }
    return <main className="standalone-editor"><OfficeEditor documentId={editorId} fullscreen onClose={()=>window.location.assign(`/?document=${editorId}`)}/></main>;
  }
  const title =
    navigation.find((n) => n[0] === view)?.[2] ?? "Администрирование";
  const isDrive = ["mine", "spaces", "departments", "shared", "recent", "favorites", "trash", "search"].includes(view);
  const canAdmin = capabilities.administration || capabilities.organization;
  const tabs = capabilities.administration
    ? [
        "overview",
        "identity",
        "organization",
        "resources",
        "governance",
        "quotas",
      ]
    : ["organization"];
  const tabLabel: Record<string, string> = {
    overview: "Обзор",
    identity: "Пользователи",
    organization: "Организация",
    resources: "Пространства и ACL",
    governance: "Хранение и Legal Hold",
    quotas: "Квоты",
  };
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark" aria-hidden="true">▰</span> NambaDrive</div>
        <nav aria-label="Основная навигация">
          {navigation.filter(([key])=>!["requests","reviews","notifications","search","profile"].includes(key)).map(([key, , label]) => (
            <button
              key={key}
              className={["requests","reviews","notifications","search","profile"].includes(key) ? "secondary-nav-item" : "primary-nav-item"}
              aria-current={view === key ? "page" : undefined}
              onClick={() => setView(key)}
            >
              <Icon name={key}/>
              {label}
            </button>
          ))}
          <details className="more-navigation"><summary>Рабочие процессы</summary>{navigation.filter(([key])=>["requests","reviews","notifications","search","profile"].includes(key)).map(([key,,label])=><button key={key} aria-current={view===key?"page":undefined} onClick={()=>setView(key)}><Icon name={key}/>{label}</button>)}</details>
          {canAdmin && (
            <button
              className="admin-link"
              aria-current={view === "administration" ? "page" : undefined}
              onClick={() => {
                setView("administration");
                if (!capabilities.administration) setAdminTab("organization");
              }}
            >
              <Icon name="administration"/>Администрирование
            </button>
          )}
        </nav>
        <div className="sidebar-user">
          <span className="avatar" aria-hidden="true">{user.display_name.slice(0, 1)}</span><button className="profile-link" aria-label="Открыть профиль" onClick={()=>setView("profile")}>{user.display_name}</button>
          <button onClick={() => void logout()}>Выйти</button>
        </div>
      </aside>
      <main className={`workspace ${isDrive ? "drive-workspace" : ""}`}>
        <header className="workspace-header">
          <h1 aria-hidden={isDrive || undefined} className={isDrive ? "sr-only" : undefined}>{title}</h1>
          {isDrive && <div className="search-host" ref={setSearchHost}/> }
          <div className="header-actions">{!isDrive && <button aria-label="Открыть поиск" onClick={() => setView("search")}><Icon name="search"/></button>}<button aria-label="Открыть уведомления" onClick={() => setView("notifications")}><Icon name="notifications"/></button></div>
        </header>
        <p role="status">{error}</p>
        {[
          "mine",
          "spaces",
          "departments",
          "shared",
          "recent",
          "favorites",
          "trash",
          "search",
        ].includes(view) && (
          <Drive
            key={view}
            view={view === "search" ? "mine" : (view as DriveView)}
            searchOnly={view === "search"}
            searchHost={searchHost}
          />
        )}
        {view === "requests" && <AccessRequests />}
        {view === "reviews" && <AccessReviews />}
        {view === "notifications" && <Notifications />}
        {view === "profile" && (
          <section className="panel">
            <h2>{user.display_name}</h2>
            <dl>
              <dt>Учётная запись</dt>
              <dd>{user.username}</dd>
              <dt>Email</dt>
              <dd>{user.email ?? "Не указан"}</dd>
            </dl>
            <Quotas />
            <Notifications />
          </section>
        )}
        {view === "administration" && canAdmin && (
          <section className="panel">
            <nav className="tabs" aria-label="Разделы администратора">
              {tabs
                .filter(
                  (t) => t !== "organization" || capabilities.organization,
                )
                .map((t) => (
                  <button
                    key={t}
                    aria-current={adminTab === t ? "page" : undefined}
                    onClick={() => setAdminTab(t)}
                  >
                    {tabLabel[t]}
                  </button>
                ))}
            </nav>
            {adminTab === "overview" && capabilities.administration && (
              <AdminDashboard />
            )}
            {adminTab === "identity" && capabilities.administration && (
              <IdentityAdmin />
            )}
            {adminTab === "organization" && capabilities.organization && (
              <OrganizationAdmin />
            )}
            {adminTab === "resources" && capabilities.administration && (
              <ResourceAdmin />
            )}
            {adminTab === "governance" && capabilities.administration && (
              <Governance />
            )}
            {adminTab === "quotas" && capabilities.administration && <Quotas />}
          </section>
        )}
      </main>
    </div>
  );
}
