import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { characterBadges, characterPhotoUrl, type SavedCharacter } from "../../api/characters";
import { useCharactersStore } from "../../store/references";
import "../models.css";

/** /models — the saved models (kind "character" references) as a page of
 * its own, inside the /clips layout. Models get here from step 1 of the
 * wizard ("★ Lưu người mẫu") and go back in through "Chọn từ thư viện". */
export function ModelsPage() {
  const items = useCharactersStore((s) => s.items);
  const loaded = useCharactersStore((s) => s.loaded);
  const error = useCharactersStore((s) => s.error);
  const load = useCharactersStore((s) => s.load);

  useEffect(() => { void load(true); }, [load]);
  useEffect(() => {
    const prev = document.title;
    document.title = "Người mẫu đã lưu · Flowboard";
    return () => { document.title = prev; };
  }, []);

  return (
    <>
      <header className="qt-header">
        <span className="qt-header__crumb">Người mẫu đã lưu</span>
      </header>
      <div className="qt-home">
        <div className="qt-card__head">
          <div>
            <div className="qt-card__eyebrow">Thư viện</div>
            <h2 className="qt-card__title">
              Người mẫu đã lưu{loaded && <span className="qt-models-page__count"> · {items.length}</span>}
            </h2>
          </div>
          <button type="button" className="qt-btn qt-btn--ghost qt-btn--small" onClick={() => void load(true)}>Tải lại</button>
        </div>

        <div className="qt-models-page__hint">
          <strong>Dùng lại một người mẫu cho sản phẩm khác:</strong> mở clip → <strong>Bước 1 · Người mẫu</strong> → bấm
          "👤 Chọn từ thư viện" → "Dùng người mẫu này". Ảnh người mẫu sẽ thay cho ảnh tạo mới và các cảnh lấy nó làm tham chiếu.
          <ol>
            <li>Thêm người mẫu: ở Bước 1, tạo người mẫu (hoặc upload ảnh người thật) rồi bấm <strong>★ Lưu người mẫu</strong>.</li>
            <li>Đổi tên: bấm vào tên trên thẻ. Xoá chỉ bỏ khỏi thư viện, clip đã dùng người mẫu đó không bị ảnh hưởng.</li>
          </ol>
        </div>

        {error && <div className="qt-banner qt-banner--error">Không tải được thư viện: {error}</div>}

        {loaded && items.length === 0 && !error && (
          <div className="qt-empty qt-empty--big">Chưa có người mẫu nào — tạo một người mẫu rồi bấm ★ Lưu.</div>
        )}

        <div className="qt-home__grid">
          {!loaded && Array.from({ length: 4 }, (_, i) => (
            <div key={`sk-${i}`} className="qt-model-card qt-model-card--skeleton" aria-hidden="true">
              <span className="qt-model-card__photo qt-skeleton" />
              <span className="qt-skeleton qt-skeleton--line" />
              <span className="qt-skeleton qt-skeleton--line qt-skeleton--short" />
            </div>
          ))}
          {loaded && items.map((c) => <ModelCard key={c.id} item={c} />)}
        </div>
      </div>
    </>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function ModelCard({ item }: { item: SavedCharacter }) {
  const rename = useCharactersStore((s) => s.rename);
  const remove = useCharactersStore((s) => s.remove);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.label);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function startEdit() {
    setDraft(item.label);
    setEditing(true);
  }

  async function commitRename() {
    const next = draft.trim();
    setEditing(false);
    if (!next || next === item.label) return;
    setBusy(true);
    setErr(null);
    try {
      await rename(item.id, next);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "không đổi tên được");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!window.confirm(`Xoá người mẫu "${item.label}" khỏi thư viện? Clip đã dùng người mẫu này vẫn giữ ảnh.`)) return;
    setBusy(true);
    setErr(null);
    try {
      await remove(item.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "không xoá được");
      setBusy(false);
    }
  }

  const badges = characterBadges(item.meta);
  const date = formatDate(item.createdAt);

  return (
    <div className="qt-model-card">
      <img className="qt-model-card__photo" src={characterPhotoUrl(item)} alt={item.label} loading="lazy" />
      {editing ? (
        <input
          className="qt-model-card__rename"
          autoFocus
          value={draft}
          maxLength={120}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commitRename()}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); void commitRename(); }
            if (e.key === "Escape") { e.preventDefault(); setEditing(false); }
          }}
        />
      ) : (
        <div className="qt-model-card__name">
          <span title={item.label}>{item.label}</span>
          <button type="button" className="qt-link" disabled={busy} onClick={startEdit} title="Đổi tên">✎</button>
        </div>
      )}
      {badges.length > 0 && (
        <div className="qt-badges">
          {badges.map((b) => <span key={b} className="qt-badge">{b}</span>)}
        </div>
      )}
      <div className="qt-model-card__meta">
        {date && <>Lưu ngày {date}</>}
        {item.meta.product && <>{date ? " · " : ""}từ "{item.meta.product}"</>}
        {item.meta.extras && <div title={item.meta.extras}>{item.meta.extras}</div>}
      </div>
      {err && <p className="product-form__error" role="alert">{err}</p>}
      <div className="qt-row qt-row--tight qt-model-card__actions">
        {item.sourceBoardId !== null && (
          <Link className="qt-link" to={`/clips/${item.sourceBoardId}`} title="Mở clip đã tạo ra người mẫu này">Mở clip gốc ↗</Link>
        )}
        <button type="button" className="qt-link qt-link--danger" disabled={busy} onClick={() => void onDelete()}>Xoá</button>
      </div>
    </div>
  );
}
