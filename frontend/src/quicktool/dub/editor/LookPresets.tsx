import { useEffect, useRef, useState } from "react";
import {
  deleteDecorPreset, getDefaultLook, listLookPresets, markDecorPresetUsed, saveLookPreset, setDefaultLook, updateLookPreset,
  type DecorPreset, type LookPresetData,
} from "../../../api/dub";
import { toast } from "../../../store/toast";
import { askChoice, askConfirm, askText } from "../../../components/Dialogs";
import { LookThumb } from "./LookThumb";

/** Which template each clip was last put on (job id → template id), so "Lưu" can offer to update that one. */
const APPLIED_KEY = "dflow.template.applied";
const APPLIED_KEEP = 300;

function readApplied(): Record<string, number> {
  try {
    const v = JSON.parse(localStorage.getItem(APPLIED_KEY) || "{}");
    return v && typeof v === "object" ? v as Record<string, number> : {};
  } catch {
    return {};
  }
}
function rememberApplied(jobId: string | undefined, id: number | null) {
  if (!jobId) return;
  try {
    const all = readApplied();
    delete all[jobId];
    if (id) all[jobId] = id;
    const keys = Object.keys(all);
    for (const k of keys.slice(0, Math.max(0, keys.length - APPLIED_KEEP))) delete all[k];
    localStorage.setItem(APPLIED_KEY, JSON.stringify(all));
  } catch { /* private window: the dialog just won't offer "update" */ }
}

/** ★ marked first, then the ones used most, then the newest (same order as the agent's list). */
function sorted(list: DecorPreset[]): DecorPreset[] {
  return [...list].sort((a, b) => Number(!!b.favorite) - Number(!!a.favorite) || (b.uses ?? 0) - (a.uses ?? 0) || b.id - a.id);
}

function summary(p: DecorPreset): string {
  const d = p.data as LookPresetData;
  const c = d.layout?.canvas;
  const bg = c && c.fit !== "crop" && c.fit !== "blur" && c.fit !== "black"
    ? `nền ${c.fit === "grid" ? "lưới" : c.fit === "color" ? "màu" : c.fit === "video" ? "video" : "ảnh"}` : "";
  const blurs = d.layout?.blurs?.length ?? (d.layout?.blur ? 1 : 0);
  return [c ? `khung ${c.aspect}` : "", bg, blurs ? `${blurs} vùng mờ` : "", d.layout?.frame ? "khung trang trí" : "",
          d.layout?.mascot?.media_id ? "nhân vật" : "", d.highlights?.on ? "nhấn chữ" : "", d.engine === "remotion" ? "phụ đề đẹp" : "",
          p.uses ? `dùng ${p.uses} lần` : ""].filter(Boolean).join(" · ");
}

/**
 * "★ Template": the whole look of a clip — subtitle place / size / style, blur boxes, output format, frame, sticker,
 * key-moment settings — kept under a name and put on any other clip in one click, so every clip of a page looks the
 * same without redoing it. A template can be ★ marked (listed first), renamed, updated with the clip being edited,
 * and one can be the default for new videos (the start forms pick it).
 */
export function LookPresets({ jobId, current, readOnly, onApply }: {
  /** the clip being edited (remembers which template it was put on) */
  jobId?: string;
  /** the editor's look right now (what "Lưu" keeps) */
  current: LookPresetData;
  readOnly: boolean;
  onApply: (data: LookPresetData, name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [presets, setPresets] = useState<DecorPreset[] | null>(null);
  const [defaultId, setDefaultId] = useState<number | null>(null);
  const [appliedId, setAppliedId] = useState<number | null>(() => (jobId ? readApplied()[jobId] ?? null : null));
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const menuForRef = useRef<number | null>(null);
  menuForRef.current = menuFor;

  useEffect(() => { setAppliedId(jobId ? readApplied()[jobId] ?? null : null); }, [jobId]);

  useEffect(() => {
    if (!open) { setMenuFor(null); return; }
    void listLookPresets().then((l) => setPresets(sorted(l))).catch(() => setPresets([]));
    void getDefaultLook().then((d) => setDefaultId(d.id)).catch(() => undefined);
    const onDoc = (e: MouseEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest(".dlg-backdrop")) return; // the name / "lưu thế nào" boxes this popover opened
      if (box.current && !box.current.contains(el)) { setOpen(false); return; }
      if (!el.closest(".dx-presets__menu, .dx-presets__more")) setMenuFor(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || document.querySelector(".dlg-backdrop")) return; // a dialog on top takes its own Esc
      if (menuForRef.current !== null) setMenuFor(null); else setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const fail = (e: unknown) => toast.error(e instanceof Error ? e.message : String(e));
  const replace = (row: DecorPreset) => setPresets((list) => sorted((list ?? []).map((x) => (x.id === row.id ? row : x))));
  const markApplied = (id: number | null) => { setAppliedId(id); rememberApplied(jobId, id); };
  const applied = (presets ?? []).find((p) => p.id === appliedId) ?? null;

  async function save() {
    if (applied) {
      const pick = await askChoice(`Clip này đang theo template "${applied.name}". Lưu chỉnh sửa hiện tại thế nào?`, [
        { value: "over", primary: true, label: `Cập nhật template "${applied.name}"`,
          hint: "Ghi đè bằng chỉnh sửa hiện tại. Video đã xuất trước đó không đổi; lần sau áp template này sẽ ra kiểu mới." },
        { value: "new", label: "Lưu thành template mới", hint: `Giữ nguyên "${applied.name}", tạo thêm một template khác.` },
      ]);
      if (pick === null) return;
      if (pick === "over") { await overwrite(applied, false); return; }
    }
    const n = (presets ?? []).length + 1;
    const name = await askText("Tên template (VD: Page vũ trụ — phụ đề vàng, khung 9:16):", `Template ${n}`);
    if (name === null) return;
    setBusy(true);
    try {
      const first = !(presets ?? []).length;
      const row = await saveLookPreset(name.trim() || `Template ${n}`, current);
      setPresets((list) => sorted([row, ...(list ?? [])]));
      markApplied(row.id);
      if (first) { await setDefaultLook(row.id); setDefaultId(row.id); }
      toast.success(`Đã lưu template "${row.name}"${first ? " và đặt làm mặc định cho video mới" : ""}. `
        + "Với clip khác: mở ★ Template → Áp dụng → Xuất lại video.");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function overwrite(p: DecorPreset, ask: boolean) {
    setMenuFor(null);
    if (ask && !await askConfirm(`Ghi đè template "${p.name}" bằng chỉnh sửa của clip này? Video đã xuất trước đó không đổi.`,
                                 { ok: "Ghi đè" })) return;
    setBusy(true);
    try {
      const row = await updateLookPreset(p.id, { data: current });
      replace(row);
      markApplied(row.id);
      toast.success(`Đã cập nhật template "${row.name}".`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  function apply(p: DecorPreset) {
    onApply(p.data as LookPresetData, p.name);
    markApplied(p.id);
    void markDecorPresetUsed(p.id).catch(() => undefined);
    setOpen(false);
  }
  async function star(p: DecorPreset) {
    replace({ ...p, favorite: !p.favorite });
    try {
      replace(await updateLookPreset(p.id, { favorite: !p.favorite }));
    } catch (e) {
      replace(p);
      fail(e);
    }
  }
  async function rename(p: DecorPreset) {
    setMenuFor(null);
    const name = await askText("Tên mới của template:", p.name);
    if (name === null || !name.trim() || name.trim() === p.name) return;
    try {
      replace(await updateLookPreset(p.id, { name: name.trim() }));
    } catch (e) {
      fail(e);
    }
  }
  async function makeDefault(p: DecorPreset | null) {
    setMenuFor(null);
    try {
      await setDefaultLook(p?.id ?? null);
      setDefaultId(p?.id ?? null);
      toast.success(p ? `"${p.name}" là template mặc định — video mới (lồng tiếng, cắt video) tự dùng. Clip đang mở: bấm Áp dụng.`
                      : "Đã bỏ template mặc định.");
    } catch (e) {
      fail(e);
    }
  }
  async function remove(p: DecorPreset) {
    setMenuFor(null);
    if (!await askConfirm(`Xoá template "${p.name}"? Các clip đã dùng không đổi.`, { ok: "Xoá", danger: true })) return;
    try {
      await deleteDecorPreset(p.id);
      setPresets((list) => (list ?? []).filter((x) => x.id !== p.id));
      if (defaultId === p.id) setDefaultId(null);
      if (appliedId === p.id) markApplied(null);
    } catch (e) {
      fail(e);
    }
  }

  return (
    <div className="dx-presets" ref={box}>
      <button type="button" className={`qt-btn qt-btn--small${open ? " is-on" : ""}`} onClick={() => setOpen((o) => !o)}
              aria-expanded={open} title="Template: lưu kiểu phụ đề / vùng mờ / khung xuất / khung / nhân vật / nhấn chữ của clip này, dùng lại cho clip khác">
        ★ Template
      </button>
      {open && (
        <div className="dx-presets__pop" role="dialog" aria-label="Template">
          <div className="dx-presets__head">
            <strong>Template</strong>
            <button type="button" className="qt-btn qt-btn--small qt-btn--accent" disabled={busy || readOnly} onClick={() => void save()}>
              {applied ? "★ Lưu template…" : "★ Lưu template mới"}
            </button>
          </div>
          <p className="dx-presets__tip">Template = vị trí / cỡ / kiểu phụ đề, vùng mờ, khung xuất + nền, khung trang trí, nhân vật / logo, nhấn chữ
            (chữ và mốc giờ của từng clip thì không). <b>Áp dụng</b> rồi bấm Xuất lại video. Bấm <b>☆</b> để ghim lên đầu, <b>⋯</b> để đổi tên,
            cập nhật, đặt mặc định cho video mới.</p>
          {applied && <p className="dx-presets__now">Clip này đang theo template <b>{applied.name}</b> — chỉnh xong bấm "★ Lưu template…" để cập nhật nó.</p>}
          {presets === null ? <small className="qt-card__hint">Đang tải…</small>
            : presets.length === 0 ? <small className="qt-card__hint">Chưa có template nào — chỉnh clip này ưng ý rồi bấm "★ Lưu template mới".</small>
            : (
              <ul className="dx-presets__list">
                {presets.map((p) => (
                  <li key={p.id} className={`${p.id === defaultId ? "is-default" : ""}${p.id === appliedId ? " is-applied" : ""}`}>
                    <button type="button" className={`dx-presets__star${p.favorite ? " is-on" : ""}`} onClick={() => void star(p)}
                            aria-pressed={!!p.favorite} aria-label={p.favorite ? `Bỏ yêu thích ${p.name}` : `Yêu thích ${p.name}`}
                            title={p.favorite ? "Bỏ ghim" : "Yêu thích — ghim lên đầu danh sách"}>
                      {p.favorite ? "★" : "☆"}
                    </button>
                    <LookThumb preset={p} width={40} />
                    <div className="dx-presets__info">
                      <strong title={p.name}>{p.name}</strong>
                      <span className="dx-presets__tags">
                        {p.id === appliedId && <em className="dx-presets__tag dx-presets__tag--on">đang dùng</em>}
                        {p.id === defaultId && <em className="dx-presets__tag">mặc định</em>}
                      </span>
                      <small>{summary(p)}</small>
                    </div>
                    <button type="button" className="qt-btn qt-btn--small qt-btn--accent dx-presets__apply" disabled={readOnly} onClick={() => apply(p)}
                            title="Đưa template này vào clip đang mở — xem trước rồi bấm Xuất lại video">Áp dụng</button>
                    <button type="button" className={`dx-presets__more${menuFor === p.id ? " is-on" : ""}`} aria-haspopup="menu"
                            aria-expanded={menuFor === p.id} aria-label={`Thêm cho ${p.name}`} title="Đổi tên, cập nhật, mặc định, xoá"
                            onClick={() => setMenuFor((m) => (m === p.id ? null : p.id))}>⋯</button>
                    {menuFor === p.id && (
                        <div className="dx-presets__menu" role="menu">
                          <button type="button" role="menuitem" onClick={() => void rename(p)}>✎ Đổi tên</button>
                          <button type="button" role="menuitem" disabled={readOnly || busy} onClick={() => void overwrite(p, true)}>⤓ Cập nhật bằng clip này</button>
                          <button type="button" role="menuitem" onClick={() => void makeDefault(p.id === defaultId ? null : p)}>
                            {p.id === defaultId ? "Bỏ mặc định" : "Đặt mặc định cho video mới"}
                          </button>
                          <button type="button" role="menuitem" className="is-danger" onClick={() => void remove(p)}>🗑 Xoá</button>
                        </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
        </div>
      )}
    </div>
  );
}
