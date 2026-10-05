import { useEffect, useState } from "react";

type Discovery = {
  id: string;
  name: string;
  type: string;
  owner_id: string;
  department_id: string;
};
type RequestRow = {
  id: string;
  name: string;
  requested_by: string;
  permission_id: string;
  reason: string;
  status: string;
  requested_until: string | null;
};
const labels: Record<string, string> = {
  VIEW: "Сведения о документе",
  EDIT: "Редактирование",
  DOWNLOAD: "Скачивание",
};
async function api(path: string, method = "GET", body?: object) {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (method !== "GET") {
    const csrf = await fetch("/api/v1/auth/csrf");
    if (!csrf.ok) throw new Error("Войдите повторно");
    headers["X-CSRF-Token"] = (await csrf.json()).data.csrf_token as string;
  }
  const response = await fetch("/api/v1/access-requests" + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok)
    throw new Error(
      "Заявка недоступна: проверьте права, срок и повторные заявки",
    );
  return (await response.json()).data;
}

export function RequestAccess({
  documentId,
  permissions = ["VIEW", "EDIT", "DOWNLOAD"],
}: {
  documentId: string;
  permissions?: string[];
}) {
  const [permission, setPermission] = useState(permissions[0] ?? "VIEW");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [status, setStatus] = useState("");
  async function submit() {
    try {
      await api("", "POST", {
        resource_id: documentId,
        permission,
        reason,
        valid_until: until ? new Date(until).toISOString() : null,
      });
      setStatus("Заявка отправлена владельцу и менеджерам отдела");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Ошибка");
    }
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label>
        Запросить доступ{" "}
        <select
          value={permission}
          onChange={(e) => setPermission(e.target.value)}
        >
          {Object.entries(labels)
            .filter(([value]) => permissions.includes(value))
            .map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
        </select>
      </label>
      <label>
        Причина{" "}
        <input
          required
          maxLength={2000}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <label>
        Доступ до (необязательно){" "}
        <input
          type="datetime-local"
          value={until}
          onChange={(e) => setUntil(e.target.value)}
        />
      </label>
      <button>Отправить заявку</button>
      <span role="status">{status}</span>
    </form>
  );
}

function Decision({
  row,
  onDecided,
}: {
  row: RequestRow;
  onDecided: () => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [status, setStatus] = useState("");
  async function decide(action: "approve" | "deny") {
    try {
      await api(`/${row.id}/${action}`, "POST", {
        reason,
        valid_until: until ? new Date(until).toISOString() : null,
      });
      await onDecided();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Ошибка");
    }
  }
  return (
    <div>
      <label>
        Причина решения{" "}
        <input
          required
          maxLength={2000}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <label>
        Ограничить срок{" "}
        <input
          type="datetime-local"
          value={until}
          onChange={(e) => setUntil(e.target.value)}
        />
      </label>
      <button disabled={!reason.trim()} onClick={() => void decide("approve")}>
        Одобрить
      </button>
      <button disabled={!reason.trim()} onClick={() => void decide("deny")}>
        Отклонить
      </button>
      <p role="status">{status}</p>
    </div>
  );
}

export function AccessRequests() {
  const [rows, setRows] = useState<RequestRow[]>([]);
  const [inbox, setInbox] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Discovery[]>([]);
  const [status, setStatus] = useState("");
  async function reload() {
    setRows((await api(inbox ? "/inbox" : "/mine")) as RequestRow[]);
  }
  useEffect(() => {
    let active = true;
    api(inbox ? "/inbox" : "/mine")
      .then((data) => {
        if (active) setRows(data as RequestRow[]);
      })
      .catch(() => {
        if (active) setStatus("Не удалось получить заявки");
      });
    return () => {
      active = false;
    };
  }, [inbox]);
  async function discover() {
    try {
      setFound(
        (await api("/discovery?q=" + encodeURIComponent(query))) as Discovery[],
      );
      setStatus("");
    } catch {
      setFound([]);
      setStatus("Поиск доступа недоступен");
    }
  }
  return (
    <section>
      <h2>Заявки на доступ</h2>
      <button onClick={() => setInbox(false)}>Мои заявки</button>
      <button onClick={() => setInbox(true)}>На согласование</button>
      <button
        onClick={() =>
          void reload().catch(() => setStatus("Обновление недоступно"))
        }
      >
        Обновить
      </button>
      <ul>
        {rows.map((row) => (
          <li key={row.id}>
            <strong>{row.name}</strong> · {labels[row.permission_id]} ·{" "}
            {row.status}
            <p>
              Заявитель: {row.requested_by}. {row.reason}
            </p>
            {row.requested_until && (
              <p>До {new Date(row.requested_until).toLocaleString()}</p>
            )}
            {inbox && <Decision row={row} onDecided={reload} />}
          </li>
        ))}
      </ul>
      <h3>Найти документ для запроса доступа</h3>
      <p>
        Здесь отображаются только сведения, открытые для обнаружения владельцем
        пространства.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void discover();
        }}
      >
        <label>
          Имя документа{" "}
          <input
            required
            minLength={2}
            maxLength={200}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <button>Найти</button>
      </form>
      <p role="status">{status}</p>
      <ul>
        {found.map((row) => (
          <li key={row.id}>
            <strong>{row.name}</strong> · {row.type}
            <p>
              Владелец: {row.owner_id} · Отдел: {row.department_id}
            </p>
            <RequestAccess documentId={row.id} />
          </li>
        ))}
      </ul>
    </section>
  );
}
