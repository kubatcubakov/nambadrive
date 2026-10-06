import { useEffect, useState } from "react";

type Resource = { id: string; name: string; resource_type: string };
type Binding = {
  id: string;
  user_id: string;
  role_id: string;
  revoked_at: string | null;
};
type Entry = {
  id: string;
  principal_type: string;
  principal_id: string;
  permission_id: string;
  effect: string;
  revoked_at: string | null;
};

export function ResourceAdmin({ resourceId = "" }: { resourceId?: string }) {
  const [departments, setDepartments] = useState<{id:string;name:string}[]>([]);
  const [users, setUsers] = useState<{id:string;display_name:string;enabled:boolean}[]>([]);
  useEffect(() => {
    let active=true;
    fetch('/api/v1/admin/organization').then(async r=>{if(r.ok){const d=await r.json();if(active)setDepartments(d.data.departments)}}).catch(()=>{});
    fetch('/api/v1/identity').then(async r=>{if(r.ok){const d=await r.json();if(active)setUsers(d.data.users)}}).catch(()=>{});
    return()=>{active=false};
  }, []);
  const [rows, setRows] = useState<Resource[]>([]);
  const [parent, setParent] = useState("");
  const [department, setDepartment] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("SPACE");
  const [resource, setResource] = useState(resourceId);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [principal, setPrincipal] = useState("");
  const [principalType, setPrincipalType] = useState("USER");
  const [permission, setPermission] = useState("VIEW");
  const [effect, setEffect] = useState("ALLOW");
  const [reason, setReason] = useState("");
  const [propagate, setPropagate] = useState(false);
  const [inherit, setInherit] = useState(true);
  const [classification, setClassification] = useState("INTERNAL");
  const [expiry, setExpiry] = useState("");
  const [status, setStatus] = useState("");
  const [role, setRole] = useState("READER");
  const [bindings, setBindings] = useState<Binding[]>([]);

  async function request(path: string, method = "GET", body?: object) {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (method !== "GET") {
      const csrf = await fetch("/api/v1/auth/csrf");
      if (!csrf.ok) throw new Error("Войдите повторно");
      headers["X-CSRF-Token"] = (
        (await csrf.json()) as { data: { csrf_token: string } }
      ).data.csrf_token;
    }
    const response = await fetch("/api/v1/resources" + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) throw new Error("Запрос отклонён: проверьте права и данные");
    return (await response.json()) as { data: unknown };
  }
  async function run(action: () => Promise<void>) {
    try {
      await action();
      setStatus("Изменения сохранены");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Операция не выполнена");
    }
  }
  async function load() {
    setRows(
      (await request(parent ? "?parent_id=" + encodeURIComponent(parent) : ""))
        .data as Resource[],
    );
  }
  async function loadAcl() {
    setEntries((await request("/" + resource + "/acl")).data as Entry[]);
  }
  async function loadBindings() {
    setBindings(
      (await request("/" + resource + "/role-bindings")).data as Binding[],
    );
  }
  return (
    <section>
      <h2>{resourceId ? "Настройка доступа" : "Пространства и права"}</h2>
      <p role="status">{status}</p>
      {!resourceId && <details className="resource-create" open><summary>Создать пространство или папку</summary>
      <label>
        Родительская папка (UUID, для пространства не требуется){" "}
        <input value={parent} onChange={(e) => setParent(e.target.value)} />
      </label>
      <button onClick={() => void run(load)}>Показать содержимое</button>
      <ul>
        {rows.map((row) => (
          <li key={row.id}>
            <button
              onClick={() => {
                setResource(row.id);
                setParent(row.id);
                setEntries([]);
              }}
            >
              {row.name} ({row.resource_type})
            </button>{" "}
            {row.id}
          </li>
        ))}
      </ul>
      <label>
        Название <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Тип ресурса{" "}
        <select value={type} onChange={(e) => setType(e.target.value)}>
          <option>SPACE</option>
          <option>FOLDER</option>
          <option>DOCUMENT</option>
        </select>
      </label>
      <label>
        Отдел{" "}
        {departments.length ? <select value={department} onChange={e=>setDepartment(e.target.value)}><option value="">Выберите отдел</option>{departments.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select> : <input placeholder="UUID отдела" value={department} onChange={e=>setDepartment(e.target.value)}/> }
      </label>
      <label>
        Классификация{" "}
        <select
          value={classification}
          onChange={(e) => setClassification(e.target.value)}
        >
          {["PUBLIC", "INTERNAL", "CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"].map(
            (c) => (
              <option key={c}>{c}</option>
            ),
          )}
        </select>
      </label>
      <label>
        <input
          type="checkbox"
          checked={inherit}
          onChange={(e) => setInherit(e.target.checked)}
        />
        Наследовать права
      </label>
      <button className="primary" disabled={!name.trim() || !department || (type !== "SPACE" && !parent)}
        onClick={() =>
          void run(async () => {
            await request("", "POST", {
              resource_type: type,
              name,
              department_id: department,
              parent_id: type === "SPACE" ? null : parent || null,
              inherit_acl: inherit,
              classification,
            });
            await load();
          })
        }
      >
        Создать ресурс
      </button></details>}
      <details className="acl-controls"><summary>Расширенные права и наследование</summary>
      <label>
        Ресурс для настройки (UUID){" "}
        <input value={resource} onChange={(e) => setResource(e.target.value)} />
      </label>
      <button onClick={() => void run(loadAcl)}>Загрузить права</button>
      <button
        disabled={!resource || !reason.trim()}
        onClick={() =>
          void run(async () => {
            await request(`/${resource}/security`, "PUT", {
              classification,
              inherit_acl: inherit,
              reason,
            });
          })
        }
      >
        Сохранить классификацию и наследование выбранного ресурса
      </button>
      <ul>
        {entries.map((entry) => (
          <li key={entry.id}>
            {entry.principal_type} {entry.principal_id} {entry.effect}{" "}
            {entry.permission_id}{" "}
            {entry.revoked_at ? (
              "(revoked)"
            ) : (
              <button
                onClick={() =>
                  void run(async () => {
                    await request(`/${resource}/acl/${entry.id}`, "DELETE");
                    await loadAcl();
                  })
                }
              >
                Отозвать
              </button>
            )}
          </li>
        ))}
      </ul>
      <button onClick={() => void run(loadBindings)}>Загрузить роли</button>
      <ul>
        {bindings.map((b) => (
          <li key={b.id}>
            {b.user_id} — {b.role_id}{" "}
            {b.revoked_at ? (
              "(revoked)"
            ) : (
              <button
                onClick={() =>
                  void run(async () => {
                    await request(
                      `/${resource}/role-bindings/${b.id}`,
                      "DELETE",
                    );
                    await loadBindings();
                  })
                }
              >
                Отозвать роль
              </button>
            )}
          </li>
        ))}
      </ul>
      <label>
        Role{" "}
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option>EDITOR</option>
          <option>REVIEWER</option>
          <option>READER</option>
          <option>GUEST</option>
        </select>
      </label>
      <button
        onClick={() =>
          void run(async () => {
            await request(`/${resource}/role-bindings`, "POST", {
              user_id: principal,
              role_name: role,
              valid_until: expiry ? new Date(expiry).toISOString() : null,
            });
            await loadBindings();
          })
        }
      >
        Назначить роль выбранному сотруднику
      </button>
      <label>
        Тип получателя{" "}
        <select
          value={principalType}
          onChange={(e) => {setPrincipalType(e.target.value);setPrincipal("")}}
        >
          <option>USER</option>
          <option>DEPARTMENT</option>
          <option>ROLE</option>
        </select>
      </label>
      <label>
        Получатель прав{" "}
        {principalType==='USER' && users.length ? <select value={principal} onChange={e=>setPrincipal(e.target.value)}><option value="">Выберите сотрудника</option>{users.filter(u=>u.enabled).map(u=><option key={u.id} value={u.id}>{u.display_name}</option>)}</select> : principalType==='DEPARTMENT' && departments.length ? <select value={principal} onChange={e=>setPrincipal(e.target.value)}><option value="">Выберите отдел</option>{departments.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select> : <input placeholder="UUID получателя" value={principal} onChange={e=>setPrincipal(e.target.value)}/> }
      </label>
      <label>
        Разрешение{" "}
        <select
          value={permission}
          onChange={(e) => setPermission(e.target.value)}
        >
          {"VIEW PREVIEW CREATE EDIT RENAME MOVE COPY DELETE DOWNLOAD PRINT CLIPBOARD_COPY UPLOAD_NEW_VERSION CREATE_FOLDER SHARE CHANGE_ACL VIEW_VERSION_HISTORY RESTORE_VERSION EXPORT_PDF RESTORE EXTERNAL_SHARE REQUEST_ACCESS_DISCOVERY"
            .split(" ")
            .map((p) => (
              <option key={p}>{p}</option>
            ))}
        </select>
      </label>
      <label>
        Действие правила{" "}
        <select value={effect} onChange={(e) => setEffect(e.target.value)}>
          <option>ALLOW</option>
          <option>DENY</option>
        </select>
      </label>
      <label>
        <input
          type="checkbox"
          checked={propagate}
          onChange={(e) => setPropagate(e.target.checked)}
        />
        Применять к вложенным ресурсам
      </label>
      <label>
        Причина{" "}
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <label>
        Срок действия (необязательно){" "}
        <input
          type="datetime-local"
          value={expiry}
          onChange={(e) => setExpiry(e.target.value)}
        />
      </label>
      <button
        onClick={() =>
          void run(async () => {
            await request(`/${resource}/acl`, "POST", {
              principal_type: principalType,
              principal_id: principal,
              permission,
              effect,
              reason,
              propagate_to_children: propagate,
              valid_until: expiry ? new Date(expiry).toISOString() : null,
            });
            await loadAcl();
          })
        }
      >
        Add ACL entry
      </button>
      </details>
    </section>
  );
}
