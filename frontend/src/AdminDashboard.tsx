import { useEffect, useState } from "react";
const labels: Record<string, string> = {
  enabled_users: "Активные пользователи",
  disabled_users: "Отключённые пользователи",
  active_documents: "Активные документы",
  quarantined_versions: "Ожидают антивирус",
  infected_versions: "Вредоносные версии",
  pending_deliveries: "Доставка уведомлений",
  pending_transfers: "Передача владения",
  open_access_reviews: "Открытые пересмотры доступа",
  logical_bytes: "Логическое хранилище, байт",
};
export function AdminDashboard() {
  const [metrics, setMetrics] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    fetch("/api/v1/admin/dashboard")
      .then(async (r) => {
        if (!r.ok) throw new Error();
        const d = await r.json();
        if (active) setMetrics(d.data as Record<string, number>);
      })
      .catch(() => {
        if (active) setError("Панель недоступна");
      });
    return () => {
      active = false;
    };
  }, []);
  return (
    <section>
      <h2>Состояние NambaDrive</h2>
      <p>
        Операционные показатели. Доступ к содержимому документов проверяется
        отдельно.
      </p>
      <div className="metrics">
        {metrics &&
          Object.entries(metrics).map(([key, value]) => (
            <article key={key}>
              <span>{labels[key] ?? key}</span>
              <strong>{value.toLocaleString()}</strong>
            </article>
          ))}
      </div>
      <p role="status">{error}</p>
    </section>
  );
}
