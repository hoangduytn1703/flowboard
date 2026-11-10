import { useEffect, useRef, useState } from "react";
import {
  deleteDecorPreset, getDefaultLook, listLookPresets, markDecorPresetUsed, saveLookPreset, setDefaultLook,
  type DecorPreset, type LookPresetData,
} from "../../../api/dub";
import { toast } from "../../../store/toast";
import { askConfirm, askText } from "../../../components/Dialogs";
import { LookThumb } from "./LookThumb";

/**
 * "★ Mẫu chỉnh sửa": the whole look of a dubbed clip — subtitle place / size / style, blur boxes, output format, frame,
 * sticker, key-moment settings — kept under a name and put on any other clip in one click, so every clip of a page
 * looks the same without redoing it. One preset can be the default for new videos (the start form picks it).
 */
export function LookPresets({ current, readOnly, onApply }: {
  /** the editor's look right now (what "Lưu mẫu" keeps) */
  current: LookPresetData;
  readOnly: boolean;
  onApply: (data: LookPresetData, name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [presets, setPresets] = useState<DecorPreset[] | null>(null);
  const [defaultId, setDefaultId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    void listLookPresets().then(setPresets).catch(() => setPresets([]));
    void getDefaultLook().then((d) => setDefaultId(d.id)).catch(() => undefined);
    const onDoc = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  async function save() {
    const n = (presets ?? []).length + 1;
    const name = await askText("Tên mẫu (VD: Page vũ trụ — phụ đề vàng, khung 9:16):", `Mẫu ${n}`);
    if (name === null) return;
    setBusy(true);
    try {
      const row = await saveLookPreset(name.trim() || `Mẫu ${n}`, current);
      setPresets((list) => [row, ...(list ?? [])]);
      if (!(presets ?? []).length) { await setDefaultLook(row.id); setDefaultId(row.id); }
      toast.success(`Đã lưu mẫu "${row.name}"${!(presets ?? []).length ? " và đặt làm mặc định cho video mới" : ""}. `
        + "Với clip khác: mở ★ Mẫu → ✓ Áp dụng → Xuất lại video.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  function apply(p: DecorPreset) {
    onApply(p.data as LookPresetData, p.name);
    void markDecorPresetUsed(p.id).catch(() => undefined);
    setOpen(false);
  }
  async function makeDefault(p: DecorPreset | null) {
    try {
      await setDefaultLook(p?.id ?? null);
      setDefaultId(p?.id ?? null);
      toast.success(p ? `"${p.name}" là mẫu mặc định — video mới (lồng tiếng, cắt video) tự dùng kiểu này. Clip đang mở: bấm ✓ Áp dụng.`
                      : "Đã bỏ mẫu mặc định.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }
  async function remove(p: DecorPreset) {
    if (!await askConfirm(`Xoá mẫu "${p.name}"? Các clip đã dùng không đổi.`)) return;
    try {
      await deleteDecorPreset(p.id);
      setPresets((list) => (list ?? []).filter((x) => x.id !== p.id));
      if (defaultId === p.id) setDefaultId(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="dx-presets" ref={box}>
      <button type="button" className={`qt-btn qt-btn--small${open ? " is-on" : ""}`} onClick={() => setOpen((o) => !o)}
              title="Mẫu chỉnh sửa: lưu kiểu phụ đề / vùng mờ / khung xuất / khung / nhân vật / nhấn chữ của clip này, dùng lại cho clip khác">
        ★ Mẫu
      </button>
      {open && (
        <div className="dx-presets__pop" role="dialog" aria-label="Mẫu chỉnh sửa">
          <div className="dx-presets__head">
            <strong>Mẫu chỉnh sửa</strong>
            <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={busy || readOnly} onClick={() => void save()}>★ Lưu kiểu hiện tại</button>
          </div>
          <p className="dx-presets__tip">Một mẫu = vị trí / cỡ / độ rộng / kiểu phụ đề, các vùng mờ, khung xuất + nền, khung trang trí, nhân vật / logo,
            cài đặt nhấn chữ (chữ và mốc giờ của từng clip thì không). <b>✓ Áp dụng</b> đưa mẫu vào clip đang mở — rồi bấm Xuất lại video.
            <b> Mặc định</b> = video mới (lồng tiếng, cắt video) tự ra theo mẫu đó.</p>
          {presets === null ? <small className="qt-card__hint">Đang tải…</small>
            : presets.length === 0 ? <small className="qt-card__hint">Chưa có mẫu nào — chỉnh clip này ưng ý rồi bấm "★ Lưu kiểu hiện tại".</small>
            : (
              <ul className="dx-presets__list">
                {presets.map((p) => {
                  const d = p.data as LookPresetData;
                  const c = d.layout?.canvas;
                  const bg = c && c.fit !== "crop" && c.fit !== "blur" && c.fit !== "black" ? `nền ${c.fit === "grid" ? "lưới" : c.fit === "color" ? "màu" : c.fit === "video" ? "video" : "ảnh"}` : "";
                  const bits = [d.style, c ? `khung ${c.aspect}` : "", bg, (d.layout?.blurs?.length ?? (d.layout?.blur ? 1 : 0)) ? `${d.layout.blurs?.length ?? 1} vùng mờ` : "",
                                d.layout?.frame ? "khung trang trí" : "", d.layout?.mascot?.media_id ? "nhân vật" : "", d.highlights?.on ? "nhấn chữ" : "", d.engine === "remotion" ? "Remotion" : ""].filter(Boolean);
                  return (
                    <li key={p.id} className={p.id === defaultId ? "is-default" : ""}>
                      <LookThumb preset={p} />
                      <button type="button" className="dx-presets__use" disabled={readOnly} onClick={() => apply(p)} title="Áp mẫu này cho clip đang mở">
                        <strong>{p.id === defaultId ? "★ " : ""}{p.name}</strong>
                        <small>{bits.join(" · ")}{p.uses ? ` · dùng ${p.uses} lần` : ""}</small>
                      </button>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={readOnly} onClick={() => apply(p)}
                              title="Đưa mẫu này vào clip đang mở (khung, nền, nhân vật, vùng mờ, kiểu phụ đề…) — xem trước rồi bấm Xuất lại video">✓ Áp dụng</button>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--ghost" title={p.id === defaultId ? "Video mới (lồng tiếng, cắt video) đang tự dùng mẫu này — bấm để bỏ" : "Video mới (lồng tiếng, cắt video) tự dùng mẫu này — không đổi clip đang mở"}
                              onClick={() => void makeDefault(p.id === defaultId ? null : p)}>{p.id === defaultId ? "Mặc định ✓" : "Mặc định"}</button>
                      <button type="button" className="qt-btn qt-btn--small qt-btn--danger" title="Xoá mẫu" onClick={() => void remove(p)}>🗑</button>
                    </li>
                  );
                })}
              </ul>
            )}
        </div>
      )}
    </div>
  );
}
