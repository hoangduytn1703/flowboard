import { useEffect, useState } from "react";
import { getCloudStatus, syncCloudFiles, type CloudStatus } from "../../api/cloud";
import { toast } from "../../store/toast";

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") return body.detail;
  } catch {
    /* not JSON */
  }
  return `${res.status} ${res.statusText}`;
}

/**
 * Settings → Dữ liệu. Where the logged-in account's data lives (this
 * machine, or its Postgres schema in the cloud), the media bucket every
 * machine shares after login, and the one-time move to the cloud.
 */
export function DataFolderSection() {
  const [s, setS] = useState<CloudStatus | null>(null);
  const [s3, setS3] = useState({ endpoint: "", bucket: "", keyId: "", secret: "" });
  const [busy, setBusy] = useState<"" | "s3" | "sync" | "migrate">("");

  async function load() {
    try {
      setS(await getCloudStatus());
    } catch {
      setS(null);
    }
  }

  useEffect(() => { void load(); }, []);

  async function saveS3() {
    setBusy("s3");
    try {
      const res = await fetch("/api/cloud/s3", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(s3) });
      if (!res.ok) throw new Error(await detail(res));
      const r = (await res.json()) as { message: string };
      toast.success(r.message);
      setS3({ endpoint: "", bucket: "", keyId: "", secret: "" });
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Lưu kho file thất bại.");
    } finally {
      setBusy("");
    }
  }

  async function sync() {
    setBusy("sync");
    try {
      const r = await syncCloudFiles();
      toast.success(`Đang đẩy ${r.queued} file lên, đã tải ${r.downloaded} file về.`);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Đồng bộ file thất bại.");
    } finally {
      setBusy("");
    }
  }

  async function migrate() {
    if (!window.confirm("Chuyển dữ liệu của tài khoản này lên cloud? Bản SQLite trên máy được giữ lại làm sao lưu.")) return;
    setBusy("migrate");
    try {
      const res = await fetch("/api/cloud/migrate", { method: "POST" });
      if (!res.ok) throw new Error(await detail(res));
      const r = (await res.json()) as { moved: boolean; tables?: Record<string, number>; reason?: string };
      if (r.moved) {
        const n = Object.values(r.tables ?? {}).reduce((a, b) => a + b, 0);
        toast.success(`Đã chuyển ${n} dòng dữ liệu lên cloud. Từ giờ đăng nhập ở máy nào cũng thấy.`);
      } else {
        toast.info(r.reason === "already on cloud" ? "Tài khoản này đã ở trên cloud." : "Không có gì để chuyển.");
      }
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Chuyển dữ liệu thất bại.");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="settings-panel__section settings-panel__section--wide">
      <div className="settings-panel__label">Dữ liệu của tài khoản</div>
      {s === null ? (
        <div className="settings-panel__hint">Đang tải…</div>
      ) : (
        <>
          <div className="settings-panel__hint">
            {s.account.auth ? <>Tài khoản <strong>{s.account.username}</strong>. </> : <>Chưa bật đăng nhập (FLOWBOARD_AUTH=off). </>}
            Database: {s.account.backend === "postgres"
              ? <strong>trên cloud (Postgres) — đăng nhập ở máy nào cũng thấy.</strong>
              : <>trên máy này (<code>{s.account.storage_dir}</code>){s.central_cloud ? " — máy này đã nối cloud, bấm chuyển bên dưới." : " — máy này chưa có FLOWBOARD_CENTRAL_DB_URL trong .env."}</>}
            {" "}File media: {s.files.enabled
              ? <>bucket <code>{s.files.bucket}</code> — đã đẩy {s.files.uploaded}, đã tải {s.files.downloaded}{s.files.pending_uploads ? `, đang chờ ${s.files.pending_uploads}` : ""}.</>
              : <>chỉ trên máy này.</>}
          </div>
          {s.files.last_error && <div className="settings-panel__project-error">Lỗi đồng bộ file gần nhất: {s.files.last_error}</div>}
          <div className="qt-row">
            {s.account.auth && s.account.backend !== "postgres" && s.central_cloud && (
              <button type="button" className="flow-accounts__btn" disabled={busy !== ""} onClick={() => void migrate()}>
                {busy === "migrate" ? "Đang chuyển…" : "☁ Chuyển dữ liệu lên cloud"}
              </button>
            )}
            {s.files.enabled && (
              <button type="button" className="flow-accounts__btn" disabled={busy !== ""} onClick={() => void sync()}>
                {busy === "sync" ? "Đang đồng bộ…" : "↻ Đồng bộ file ngay"}
              </button>
            )}
          </div>
          <div className="data-sync__box">
            <strong>Kho file media (S3: Backblaze B2 / Cloudflare R2) — dùng chung cho mọi máy đăng nhập</strong>
            <input className="settings-panel__project-input" placeholder={s.files.endpoint ?? "Endpoint: s3.us-west-004.backblazeb2.com"}
                   value={s3.endpoint} onChange={(e) => setS3({ ...s3, endpoint: e.target.value })} />
            <input className="settings-panel__project-input" placeholder={s.files.bucket ?? "Tên bucket"}
                   value={s3.bucket} onChange={(e) => setS3({ ...s3, bucket: e.target.value })} />
            <input className="settings-panel__project-input" placeholder="Key ID"
                   value={s3.keyId} onChange={(e) => setS3({ ...s3, keyId: e.target.value })} />
            <input className="settings-panel__project-input" type="password" placeholder="Application key / secret"
                   value={s3.secret} onChange={(e) => setS3({ ...s3, secret: e.target.value })} />
            <div className="qt-row">
              <button type="button" className="flow-accounts__btn" disabled={busy !== "" || !s3.endpoint || !s3.bucket || !s3.keyId || !s3.secret}
                      onClick={() => void saveS3()}>
                {busy === "s3" ? "Đang kiểm tra…" : s.files.enabled ? "Đổi kho file" : "Kiểm tra & lưu"}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
