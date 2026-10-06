import { useCallback, useEffect, useState } from "react";
import { Shares } from "./Shares";
import { RequestAccess } from "./AccessRequests";
import { Versions } from "./Versions";
import { Upload } from "./Upload";
import { Search } from "./Search";
import { FileIcon } from "./Icons";
import { ResourceAdmin } from "./ResourceAdmin";

type Item = {
  id: string;
  name: string;
  resource_type: string;
  department_id: string;
  department_name?: string;
  owner_name?: string;
  size?: number;
  favorite?: boolean;
};
type Detail = Item & {
  size: number;
  mime_type: string;
  owner_user_id: string;
  sha256: string;
  metadata: {
    description?: string;
    tags?: string[];
    project_id?: string | null;
    counterparty?: string | null;
    contract_number?: string | null;
    contract_date?: string | null;
    contract_expiry?: string | null;
  };
};
function formatSize(size: number | null | undefined) {
  if (size == null) return "—";
  if (size < 1024) return `${size} байт`;
  const megabytes = size >= 1024 * 1024;
  return `${new Intl.NumberFormat("ru", {maximumFractionDigits:1}).format(size / (megabytes ? 1024*1024 : 1024))} ${megabytes ? "МБ" : "КБ"}`;
}
const classificationLabels: Record<string,string> = {PUBLIC:"Публичный",INTERNAL:"Внутренний",CONFIDENTIAL:"Конфиденциальный",STRICTLY_CONFIDENTIAL:"Строго конфиденциальный"};
async function api(path: string, method = "GET", body?: object) {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (method !== "GET") {
    const csrf = await fetch("/api/v1/auth/csrf");
    if (!csrf.ok) throw new Error("Войдите повторно");
    headers["X-CSRF-Token"] = (await csrf.json()).data.csrf_token as string;
  }
  const response = await fetch("/api/v1" + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok)
    throw new Error("Операция недоступна: проверьте права и данные");
  return (await response.json()).data;
}

export function Drive({
  view = "spaces",
  searchOnly = false,
  searchHost,
}: {
  view?:
    | "mine"
    | "spaces"
    | "departments"
    | "shared"
    | "recent"
    | "favorites"
    | "trash";
  searchOnly?: boolean;
  searchHost?: HTMLElement | null;
}) {
  const [page, setPage] = useState(1);
  const [path, setPath] = useState<Item[]>([]);
  const [rows, setRows] = useState<Item[]>([]);
  const [trash, setTrash] = useState(view === "trash");
  const [selected, setSelected] = useState<Detail | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [parentPermissions, setParentPermissions] = useState<string[]>([]);
  const [classification, setClassification] = useState("INTERNAL");
  const [inherit, setInherit] = useState(true);
  const [policyReason, setPolicyReason] = useState("");
  const [showAcl, setShowAcl] = useState(false);
  const [newOfficeName, setNewOfficeName] = useState("");
  const [newOfficeFormat, setNewOfficeFormat] = useState("docx");
  const [detailTab, setDetailTab] = useState("info");
  const [createOpen, setCreateOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [preview, setPreview] = useState(false);
  const [rename, setRename] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [counterparty, setCounterparty] = useState("");
  const [contractNumber, setContractNumber] = useState("");
  const [contractDate, setContractDate] = useState("");
  const [contractExpiry, setContractExpiry] = useState("");
  const [showParentAcl, setShowParentAcl] = useState(false);
  const [project, setProject] = useState("");
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [destination, setDestination] = useState<Item[]>([]);
  const [targets, setTargets] = useState<Item[]>([]);
  const [transfer, setTransfer] = useState<"move" | "copy" | null>(null);
  const parent = path.at(-1);
  const parentId = parent?.id;
  const listPath = trash
    ? "/drive?view=trash&page=" + page
    : parentId
      ? "/resources?parent_id=" + parentId
      : "/drive?view=" + view + "&page=" + page;
  async function reload() {
    setRows((await api(listPath)) as Item[]);
  }
  useEffect(() => {
    let active = true;
    api(listPath)
      .then((data) => {
        if (active) setRows(data as Item[]);
      })
      .catch(() => {
        if (active) setStatus("Не удалось загрузить папку");
      });
    return () => {
      active = false;
    };
  }, [listPath]);
  useEffect(() => {
    let active = true;
    setParentPermissions([]);
    if (parentId)
      api(`/resources/${parentId}/capabilities`)
        .then((p) => {
          if (active) setParentPermissions(p as string[]);
        })
        .catch(() => {
          if (active) setParentPermissions([]);
        });
    return () => {
      active = false;
    };
  }, [parentId]);
  async function run(action: () => Promise<void>) {
    try {
      setStatus("");
      await action();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Ошибка");
    }
  }
  const loadDocument = useCallback(async (id: string) => {
    setPreview(false);
    setDetailTab("info");
    setDetailsOpen(false);
    setPermissions([]);
    setSelected(null);
    setShowAcl(false);
    const detail = (await api("/documents/" + id)) as Detail;
    const allowed = (await api(`/resources/${id}/capabilities`)) as string[];
    setSelected(detail);
    setPermissions(allowed);
    setRename(detail.name);
    setClassification(
      (detail as Detail & { classification: string }).classification,
    );
    setInherit((detail as Detail & { inherit_acl: boolean }).inherit_acl);
    setProject(detail.metadata.project_id ?? "");
    setCounterparty(detail.metadata.counterparty ?? "");
    setContractNumber(detail.metadata.contract_number ?? "");
    setContractDate(detail.metadata.contract_date ?? "");
    setContractExpiry(detail.metadata.contract_expiry ?? "");
    setProjects(
      allowed.includes("EDIT")
        ? ((await api("/quotas/projects-for/" + id)) as {
            id: string;
            name: string;
          }[])
        : [],
    );
    setDescription(detail.metadata.description ?? "");
    setTags((detail.metadata.tags ?? []).join(", "));
  }, []);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("document");
    if (id)
      void loadDocument(id).catch(() =>
        setStatus("Документ по ссылке недоступен"),
      );
  }, [loadDocument]);
  async function open(item: Item) {
    if (item.resource_type !== "DOCUMENT") {
      setPage(1);
      setPath([...path, item]);
      setSelected(null);
      setCreateOpen(false);
      setUploadOpen(false);
      setParentPermissions([]);
      return;
    }
    await loadDocument(item.id);
  }
  async function browseDestination(next: Item[]) {
    setDestination(next);
    const id = next.at(-1)?.id;
    setTargets(
      (
        (await api("/resources" + (id ? "?parent_id=" + id : ""))) as Item[]
      ).filter((r) => r.resource_type !== "DOCUMENT"),
    );
  }
  return (
    <section className={`drive ${selected ? "has-document" : ""}`}>
      <Search host={searchHost}
        onOpen={async (hit) => {
          setTrash(false);
          await open(hit);
        }}
      />
      {!selected && <nav className="drive-toolbar" aria-label="Документы">
        <div className="folder-title"><h1>{parent?.name ?? ({mine:"Мои документы",spaces:"Общие пространства",departments:"Отделы",shared:"Доступные мне",recent:"Недавние",favorites:"Избранное",trash:"Корзина"}[view])}</h1></div>
        {!selected && !trash && parent && (parentPermissions.includes("CREATE") || parentPermissions.includes("CREATE_FOLDER")) && <button aria-expanded={createOpen} onClick={() => setCreateOpen(!createOpen)}>＋ Создать</button>}
        {!trash && parent && parentPermissions.includes("CREATE") && <button className="primary" aria-expanded={uploadOpen} onClick={() => setUploadOpen(!uploadOpen)}>Загрузить файлы</button>}
        <button onClick={() => void run(reload)}>Обновить</button>
      </nav>}
      {!trash && (
        <nav className="breadcrumbs" aria-label="Путь">
          <button onClick={() => {setPage(1);setPath([]);setSelected(null);setDetailsOpen(false)}}>{({mine:"Мои документы",spaces:"Общие пространства",departments:"Отделы",shared:"Доступные мне",recent:"Недавние",favorites:"Избранное",trash:"Корзина"}[view])}</button>
          {path.map((item, index) => (
            <button
              key={item.id}
              onClick={() => {
                setPath(path.slice(0, index + 1));
                setSelected(null);
              }}
            >
              {item.name}
            </button>
          ))}
        </nav>
      )}
      <p role="status">{status}</p>
      {!selected && !trash && parent && (
        <>
          {parentPermissions.includes("CHANGE_ACL") && (
            <>
              <button onClick={() => setShowParentAcl(!showParentAcl)}>
                Права пространства / папки
              </button>
              {showParentAcl && (
                <ResourceAdmin key={parent.id + "acl"} resourceId={parent.id} />
              )}
            </>
          )}
          {createOpen && parentPermissions.includes("CREATE_FOLDER") && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => {
                  await api("/resources", "POST", {
                    resource_type: "FOLDER",
                    name: newFolderName,
                    parent_id: parent.id,
                    department_id: parent.department_id,
                  });
                  setNewFolderName("");
                  await reload();
                });
              }}
            >
              <label>
                Новая папка{" "}
                <input
                  required
                  maxLength={255}
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                />
              </label>
              <button>Создать папку</button>
            </form>
          )}
          {uploadOpen && parentPermissions.includes("CREATE") && (
            <Upload key={parent.id} parentId={parent.id} />
          )}

          {createOpen && parentPermissions.includes("CREATE") && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => {
                  await api("/office/create", "POST", {
                    parent_id: parent.id,
                    name: newOfficeName,
                    format: newOfficeFormat,
                  });
                  setStatus("Документ создан и ожидает антивирусной проверки");
                  setNewOfficeName("");
                });
              }}
            >
              <label>
                Новый документ{" "}
                <input
                  required
                  value={newOfficeName}
                  onChange={(e) => setNewOfficeName(e.target.value)}
                />
              </label>
              <select
                aria-label="Формат нового документа"
                value={newOfficeFormat}
                onChange={(e) => setNewOfficeFormat(e.target.value)}
              >
                <option value="docx">Текст</option>
                <option value="xlsx">Таблица</option>
                <option value="pptx">Презентация</option>
              </select>
              <button>Создать</button>
            </form>
          )}
        </>
      )}
      {!selected && !searchOnly && (
        <><div className="file-table-heading" aria-hidden="true"><span>Название</span><span>Владелец / отдел</span><span>Размер</span><span /></div><ul className="file-list">
          {rows.map((item) => (
            <li key={item.id}>
              {trash ? (
                <>
                  <span>{item.name}</span>
                  <button
                    onClick={() =>
                      void run(async () => {
                        await api(`/documents/${item.id}/restore`, "POST");
                        await reload();
                      })
                    }
                  >
                    Восстановить
                  </button>
                </>
              ) : (
                <button onClick={() => void run(() => open(item))}>
                  <FileIcon name={item.name} type={item.resource_type}/><span>{item.name}</span>
                </button>
              )}
              {!trash && (
                <button
                  className="favorite-button"
                  aria-label={
                    item.favorite ? "Убрать из избранного" : "В избранное"
                  }
                  onClick={() =>
                    void run(async () => {
                      await api(
                        `/favorites/${item.id}`,
                        item.favorite ? "DELETE" : "PUT",
                      );
                      await reload();
                    })
                  }
                >
                  {item.favorite ? "★" : "☆"}
                </button>
              )}
              <small className="file-owner">
                {item.owner_name ?? "—"}{" "}
                {item.department_name && " · " + item.department_name}{" "}
              </small>
              <span className="file-size">{formatSize(item.size)}</span>
            </li>
          ))}
        </ul></>
      )}
      {!selected && !searchOnly && !parentId && (
        <nav aria-label="Страницы">
          <button
            disabled={page === 1}
            onClick={() => {
              setPage(page - 1);
              setSelected(null);
            }}
          >
            Предыдущая
          </button>
          <span>Страница {page}</span>
          <button
            disabled={rows.length < 100}
            onClick={() => {
              setPage(page + 1);
              setSelected(null);
            }}
          >
            Следующая
          </button>
        </nav>
      )}
      {!selected && !searchOnly && !rows.length && (
        <p className="empty-state">Здесь пока нет доступных документов</p>
      )}
      {selected && !trash && (
        <article className="document-detail">
          <div className="document-heading"><span className="file-badge">{selected.name.split(".").at(-1)?.toUpperCase()}</span><h1>{selected.name}</h1><button aria-label="Закрыть документ" onClick={() => {setSelected(null); setPreview(false); setDetailsOpen(false)}}>✕</button></div>
          <p className="document-subtitle">{selected.name.split(".").at(-1)?.toUpperCase()} · {formatSize(selected.size)}</p>
          <div className="document-actions"><button aria-label="Обновить документ" onClick={()=>void run(()=>loadDocument(selected.id))}>↻</button>

          {permissions.includes("EDIT") &&
            /\.(docx|xlsx|pptx)$/i.test(selected.name) && (
              <a className="primary editor-link" target="_blank" rel="noopener noreferrer" href={`/?editor=${selected.id}`}>
                Открыть в редакторе
              </a>
            )}
          {permissions.includes("PREVIEW") && ["application/pdf", "image/jpeg", "image/png", "text/plain", "text/csv", "application/json", "application/xml"].includes(selected.mime_type) && (
            <button onClick={() => setPreview(!preview)}>Предпросмотр</button>
          )}
          {permissions.includes("DOWNLOAD") && (
            <a href={`/api/v1/documents/${selected.id}/download`}>Скачать</a>
          )}
          {permissions.includes("SHARE") && <button onClick={()=>{setDetailTab("access");setDetailsOpen(true)}}>Поделиться</button>}
          </div>
          <button className="details-toggle" aria-expanded={detailsOpen} aria-controls="document-sidebar" onClick={()=>setDetailsOpen(!detailsOpen)}>{detailsOpen ? "Скрыть панель" : "Сведения, доступ и версии"}</button>
          <div className={`document-body ${detailsOpen ? "" : "details-collapsed"}`}><div className="document-canvas">
          {!preview && <div className="preview-placeholder"><span className="file-badge">{selected.name.split(".").at(-1)?.toUpperCase()}</span><strong>{selected.name}</strong><p>{/\.(docx|xlsx|pptx)$/i.test(selected.name) ? "Откройте документ в ONLYOFFICE с помощью кнопки выше." : "Выберите «Предпросмотр», чтобы увидеть содержимое, если формат поддерживается."}</p></div>}
          {preview && (
            <img
              className="document-preview"
              src={`/api/v1/documents/${selected.id}/preview`}
              alt="Предпросмотр документа"
              onError={() =>
                setStatus("Предпросмотр для этого файла недоступен")
              }
            />
          )}
          </div><aside id="document-sidebar" className="document-sidebar" hidden={!detailsOpen}>
          <nav className="tabs" aria-label="Панель документа">{[["info", "Сведения"], ["access", "Доступ"], ["versions", "Версии"]].map(([key, label]) => <button key={key} aria-current={detailTab === key ? "page" : undefined} onClick={() => setDetailTab(key)}>{label}</button>)}</nav>
          <div className="classification-badge">{classificationLabels[classification] ?? classification}</div>
          <section hidden={detailTab !== "info"}>
          <dl>
            <dt>Владелец</dt>
            <dd>
              {selected.owner_name ??
                rows.find((r) => r.id === selected.id)?.owner_name ??
                selected.owner_user_id}
            </dd>
            <dt>Отдел</dt>
            <dd>
              {selected.department_name ??
                rows.find((r) => r.id === selected.id)?.department_name ??
                selected.department_id}
            </dd>
          </dl>
          <p className="muted">{selected.metadata.description || "Описание не добавлено"}</p>
          {permissions.includes("RENAME") && (
            <details className="document-form"><summary>Переименовать документ</summary><form
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => {
                  await api(`/documents/${selected.id}/rename`, "POST", {
                    name: rename,
                  });
                  await reload();
                  setSelected({ ...selected, name: rename });
                });
              }}
            >
              <label>
                Имя{" "}
                <input
                  value={rename}
                  onChange={(e) => setRename(e.target.value)}
                />
              </label>
              <button>Переименовать</button>
            </form></details>
          )}
          {permissions.includes("EDIT") && (
            <details className="document-form"><summary>Изменить сведения</summary><form
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => {
                  await api(`/documents/${selected.id}/metadata`, "PUT", {
                    ...selected.metadata,
                    project_id: project || null,
                    counterparty: counterparty || null,
                    contract_number: contractNumber || null,
                    contract_date: contractDate || null,
                    contract_expiry: contractExpiry || null,
                    description,
                    tags: tags
                      .split(",")
                      .map((t) => t.trim())
                      .filter(Boolean),
                  });
                  setStatus("Описание сохранено");
                });
              }}
            >
              <label>
                Проект{" "}
                <select
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                >
                  <option value="">Без проекта</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Контрагент{" "}
                <input
                  maxLength={255}
                  value={counterparty}
                  onChange={(e) => setCounterparty(e.target.value)}
                />
              </label>
              <label>
                Номер договора{" "}
                <input
                  maxLength={255}
                  value={contractNumber}
                  onChange={(e) => setContractNumber(e.target.value)}
                />
              </label>
              <label>
                Дата договора{" "}
                <input
                  type="date"
                  value={contractDate}
                  onChange={(e) => setContractDate(e.target.value)}
                />
              </label>
              <label>
                Истекает{" "}
                <input
                  type="date"
                  value={contractExpiry}
                  onChange={(e) => setContractExpiry(e.target.value)}
                />
              </label>
              <label>
                Описание{" "}
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </label>
              <label>
                Теги через запятую{" "}
                <input value={tags} onChange={(e) => setTags(e.target.value)} />
              </label>
              <button>Сохранить</button>
            </form></details>
          )}
          {(["move", "copy"] as const).map(
            (action) =>
              permissions.includes(action.toUpperCase()) && (
                <button
                  key={action}
                  onClick={() =>
                    void run(async () => {
                      setTransfer(action);
                      await browseDestination([]);
                    })
                  }
                >
                  {action === "move" ? "Переместить" : "Копировать"}
                </button>
              ),
          )}
          </section>
          <section hidden={detailTab !== "versions"}>
          {permissions.includes("UPLOAD_NEW_VERSION") && (
            <Upload documentId={selected.id} />
          )}
          {permissions.includes("VIEW_VERSION_HISTORY") && (
            <Versions
              key={selected.id}
              documentId={selected.id}
              canRestore={permissions.includes("RESTORE_VERSION")}
            />
          )}
          </section>
          <section hidden={detailTab !== "access"}>
          {permissions.includes("SHARE") && (
            <Shares
              key={selected.id}
              documentId={selected.id}
              external={permissions.includes("EXTERNAL_SHARE")}
            />
          )}
          {permissions.includes("CHANGE_ACL") && (
            <>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(async () => {
                    await api(`/resources/${selected.id}/security`, "PUT", {
                      classification,
                      inherit_acl: inherit,
                      reason: policyReason,
                    });
                    await loadDocument(selected.id);
                    setStatus("Политика сохранена");
                  });
                }}
              >
                <label>
                  Классификация{" "}
                  <select
                    value={classification}
                    onChange={(e) => setClassification(e.target.value)}
                  >
                    {[
                      "PUBLIC",
                      "INTERNAL",
                      "CONFIDENTIAL",
                      "STRICTLY_CONFIDENTIAL",
                    ].map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={inherit}
                    onChange={(e) => setInherit(e.target.checked)}
                  />
                  Наследовать ACL
                </label>
                <label>
                  Причина{" "}
                  <input
                    required
                    maxLength={2000}
                    value={policyReason}
                    onChange={(e) => setPolicyReason(e.target.value)}
                  />
                </label>
                <button>Сохранить политику</button>
              </form>
              <button onClick={() => setShowAcl(!showAcl)}>
                Настроить права
              </button>
              {showAcl && (
                <ResourceAdmin
                  key={selected.id + "acl"}
                  resourceId={selected.id}
                />
              )}
            </>
          )}
          {(!permissions.includes("EDIT") ||
            !permissions.includes("DOWNLOAD")) && (
            <details>
              <summary>Запросить дополнительные права</summary>
              <RequestAccess
                key={selected.id + "-request"}
                documentId={selected.id}
                permissions={["EDIT", "DOWNLOAD"].filter(
                  (p) => !permissions.includes(p),
                )}
              />
            </details>
          )}
          </section>
          {permissions.includes("DELETE") && (
            <button
              onClick={() =>
                void run(async () => {
                  await api("/documents/" + selected.id, "DELETE");
                  setSelected(null);
                  await reload();
                })
              }
            >
              В корзину
            </button>
          )}
          </aside></div>
        </article>
      )}
      {transfer && selected && (
        <section aria-label="Выбор папки назначения">
          <h3>Папка назначения</h3>
          <button
            onClick={() =>
              void run(() => browseDestination(destination.slice(0, -1)))
            }
          >
            Назад
          </button>
          <p>
            {destination.map((item) => item.name).join(" / ") || "Пространства"}
          </p>
          {targets.map((item) => (
            <button
              key={item.id}
              onClick={() =>
                void run(() => browseDestination([...destination, item]))
              }
            >
              {item.name}
            </button>
          ))}
          <button
            disabled={!destination.length}
            onClick={() =>
              void run(async () => {
                await api(`/documents/${selected.id}/${transfer}`, "POST", {
                  parent_id: destination.at(-1)?.id,
                });
                setTransfer(null);
                setSelected(null);
                await reload();
              })
            }
          >
            Выбрать эту папку
          </button>
          <button onClick={() => setTransfer(null)}>Отмена</button>
        </section>
      )}
    </section>
  );
}
