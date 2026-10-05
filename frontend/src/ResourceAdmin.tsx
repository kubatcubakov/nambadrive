import { useState } from "react";

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
      if (!csrf.ok) throw new Error("Session unavailable");
      headers["X-CSRF-Token"] = (
        (await csrf.json()) as { data: { csrf_token: string } }
      ).data.csrf_token;
    }
    const response = await fetch("/api/v1/resources" + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) throw new Error("Access denied or invalid request");
    return (await response.json()) as { data: unknown };
  }
  async function run(action: () => Promise<void>) {
    try {
      await action();
      setStatus("Done");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Operation failed");
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
      <h2>Resource tree and permissions</h2>
      <p role="status">{status}</p>
      <label>
        Parent resource UUID (empty for spaces){" "}
        <input value={parent} onChange={(e) => setParent(e.target.value)} />
      </label>
      <button onClick={() => void run(load)}>Load children</button>
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
        Name <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Type{" "}
        <select value={type} onChange={(e) => setType(e.target.value)}>
          <option>SPACE</option>
          <option>FOLDER</option>
          <option>DOCUMENT</option>
        </select>
      </label>
      <label>
        Department UUID{" "}
        <input
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
        />
      </label>
      <label>
        Classification{" "}
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
        Inherit ACL
      </label>
      <button
        onClick={() =>
          void run(async () => {
            await request("", "POST", {
              resource_type: type,
              name,
              department_id: department,
              parent_id: parent || null,
              inherit_acl: inherit,
              classification,
            });
            await load();
          })
        }
      >
        Create resource
      </button>
      <label>
        ACL resource UUID{" "}
        <input value={resource} onChange={(e) => setResource(e.target.value)} />
      </label>
      <button onClick={() => void run(loadAcl)}>Load ACL</button>
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
                Revoke
              </button>
            )}
          </li>
        ))}
      </ul>
      <button onClick={() => void run(loadBindings)}>Load role bindings</button>
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
                Revoke role
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
        Assign role to user UUID below
      </button>
      <label>
        Principal type{" "}
        <select
          value={principalType}
          onChange={(e) => setPrincipalType(e.target.value)}
        >
          <option>USER</option>
          <option>DEPARTMENT</option>
          <option>ROLE</option>
        </select>
      </label>
      <label>
        Principal UUID{" "}
        <input
          value={principal}
          onChange={(e) => setPrincipal(e.target.value)}
        />
      </label>
      <label>
        Permission{" "}
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
        Effect{" "}
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
        Propagate to children
      </label>
      <label>
        Reason{" "}
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <label>
        Expiry (optional){" "}
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
    </section>
  );
}
