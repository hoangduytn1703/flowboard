// "📡 Cào video kênh" — Douyin / Bilibili channel pages (MAIN world, document_start).
//
// These two sites only give an account's video list to a real, signed-in browser: the page itself asks its API for
// it. While DFlow reads a channel (background.js handleListChannel registers this file for that moment only), this
// script keeps a small copy of what the page's OWN requests brought back — the video list answers — so the extension
// can hand DFlow the titles, dates, likes and covers. Nothing is requested, signed or clicked on the seller's behalf
// here; it only listens.
(() => {
  if (window.__dflowHooked) return;
  window.__dflowHooked = true;
  // Douyin sends its list request with an XMLHttpRequest borrowed from a blank inner frame, so this script runs in
  // every frame of the page and they all write to one store kept on the top window.
  let root = window;
  try { if (window.top && window.top.location.hostname) root = window.top; } catch (e) { return; }  // a foreign frame
  if (root.__dflowList) { hook(root.__dflowList); return; }
  const store = { platform: root.location.hostname.includes('bilibili') ? 'bilibili' : 'douyin', items: [], seen: {},
                  hasMore: null, total: null, pages: 0, refused: 0, user: null };
  root.__dflowList = store;

  const LIST = /\/aweme\/v1\/web\/aweme\/post\/|\/x\/space\/(wbi\/)?arc\/search/;
  const text = (v, n) => String(v == null ? '' : v).replace(/\s+/g, ' ').trim().slice(0, n);
  const num = (v) => (typeof v === 'number' && isFinite(v) ? v : (typeof v === 'string' && /^\d+$/.test(v) ? Number(v) : null));
  const first = (list) => (Array.isArray(list) && list.length ? String(list[0]) : '');

  function clock(v) {  // Bilibili's "12:34" / "1:02:03" → seconds
    const parts = String(v || '').split(':').map(Number);
    if (!parts.length || parts.some((p) => !isFinite(p))) return null;
    return parts.reduce((a, p) => a * 60 + p, 0) || null;
  }

  function add(item) {
    if (!item || !item.id || store.seen[item.id]) return;
    store.seen[item.id] = 1;
    store.items.push(item);
  }

  // One list answer, trimmed to what a video card needs (a Douyin item is ~20 KB as it comes).
  function take(data) {
    if (!data || typeof data !== 'object') return;
    if (Array.isArray(data.aweme_list)) {          // Douyin: /aweme/v1/web/aweme/post/
      const had = store.items.length;
      store.hasMore = !!data.has_more;
      setTimeout(() => { if (store.items.length > had) store.pages += 1; }, 0);   // the same answer may be seen twice
      for (const a of data.aweme_list) {
        if (!a || !a.aweme_id) continue;
        const st = a.statistics || {};
        const v = a.video || {};
        const author = a.author || {};
        if (!store.user && author.nickname) {
          store.user = { name: text(author.nickname, 120), avatar: first((author.avatar_thumb || {}).url_list),
                         followers: num(author.follower_count) };
        }
        add({
          id: String(a.aweme_id), title: text(a.desc, 300), created: num(a.create_time),
          duration_ms: num(v.duration) || num(a.duration), likes: num(st.digg_count), comments: num(st.comment_count),
          shares: num(st.share_count), saves: num(st.collect_count), views: num(st.play_count) || null,
          cover: first((v.cover || {}).url_list) || first((v.origin_cover || {}).url_list) || first((v.dynamic_cover || {}).url_list),
          pinned: !!a.is_top, images: Array.isArray(a.images) && a.images.length > 0,
        });
      }
      return;
    }
    const list = data.data && data.data.list && data.data.list.vlist;   // Bilibili: /x/space/wbi/arc/search
    if (Array.isArray(list)) {
      store.pages += 1;
      const page = data.data.page || {};
      store.total = num(page.count);
      for (const b of list) {
        if (!b || !b.bvid) continue;
        if (!store.user && b.author) store.user = { name: text(b.author, 120), avatar: '', followers: null };
        add({
          id: String(b.bvid), title: text(b.title, 300), created: num(b.created), duration_s: clock(b.length),
          views: num(b.play), comments: num(b.comment), likes: null, cover: String(b.pic || ''), pinned: false, images: false,
        });
      }
      store.hasMore = store.total != null ? store.items.length < store.total : list.length > 0;
    } else if (typeof data.code === 'number' && data.code !== 0) {
      store.refused += 1;                           // Bilibili says no with a code (-352, -412…)
    }
  }
  store.take = take;   // also fed by tests
  store.read = read;
  hook(store);

  function read(url, status, body) {
    if (!LIST.test(String(url || ''))) return;
    if (status >= 400) { store.refused += 1; return; }
    try { take(typeof body === 'string' ? JSON.parse(body) : body); } catch (e) { /* not JSON: an empty or blocked answer */ }
  }

  // This frame's fetch / XMLHttpRequest report to the store (functions above are hoisted; `store` is the top one).
  function hook(store) {
  const LIST = /\/aweme\/v1\/web\/aweme\/post\/|\/x\/space\/(wbi\/)?arc\/search/;
  const read = store.read;
  // Douyin's own request layer keeps its XMLHttpRequest away from listeners added here, so the list is also taken
  // where the page turns the answer into an object: JSON.parse (the page gets the very same result).
  if (store.platform === 'douyin') {
    JSON.parse = new Proxy(JSON.parse, {
      apply(target, self, args) {
        const out = Reflect.apply(target, self, args);
        try {
          const src = args[0];
          if (out && typeof src === 'string' && src.length > 500 && Array.isArray(out.aweme_list) && src.includes('"max_cursor"')) {
            store.take(out);
          }
        } catch (e) { /* never in the page's way */ }
        return out;
      },
    });
  }
  // fetch: the answer is read from a clone, the page gets its own untouched
  const realFetch = window.fetch;
  if (typeof realFetch === 'function') {
    window.fetch = new Proxy(realFetch, {
      apply(target, self, args) {
        const out = Reflect.apply(target, self, args);
        try {
          const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
          if (LIST.test(url)) out.then((r) => r.clone().text().then((t) => read(url, r.status, t))).catch(() => {});
        } catch (e) { /* never in the page's way */ }
        return out;
      },
    });
  }
  // XMLHttpRequest: note the address at open(), read the answer when it has loaded
  const proto = window.XMLHttpRequest && window.XMLHttpRequest.prototype;
  if (proto) {
    proto.open = new Proxy(proto.open, {
      apply(target, self, args) {
        try {
          const url = String(args[1] || '');
          if (LIST.test(url)) {
            self.addEventListener('load', () => {
              try {
                const kind = self.responseType;
                read(url, self.status, kind === '' || kind === 'text' ? self.responseText : self.response);
              } catch (e) { /* ignore */ }
            });
          }
        } catch (e) { /* never in the page's way */ }
        return Reflect.apply(target, self, args);
      },
    });
  }
  }
})();
