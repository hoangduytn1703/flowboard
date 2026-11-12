// Renders one composition of `frontend/src/remotion` to mp4. Called by the
// agent (services/dub_remotion.py):
//
//   node frontend/remotion/render.mjs <spec.json>
//
// spec = { composition: "DubSubtitles", src: "<abs path of the input video>",
//          out: "<abs path of the mp4 to write>", props: {...inputProps minus src},
//          concurrency?: number|string, crf?: number }
//
// Progress goes to stdout as lines "PROGRESS 0.42"; the last line is "DONE" or
// "ERROR <message>" (exit code 1). The webpack bundle is built once and cached
// in node_modules/.cache/flowboard-remotion; it is rebuilt when a file under
// src/remotion changes. The input video is served to Chrome over a local http
// server with Range support (Remotion needs a URL, not a file path).
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { ensureBrowser, renderMedia, selectComposition } from "@remotion/renderer";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const frontend = path.resolve(here, "..");
const srcDir = path.join(frontend, "src", "remotion");
const cacheDir = path.join(frontend, "node_modules", ".cache", "flowboard-remotion");
const bundleDir = path.join(cacheDir, "bundle");
const stampFile = path.join(cacheDir, "stamp.json");

function log(line) {
  process.stdout.write(line + "\n");
}

function sourceStamp() {
  const files = fs.readdirSync(srcDir).filter((f) => /\.(tsx?|css)$/.test(f)).sort();
  return files.map((f) => `${f}:${fs.statSync(path.join(srcDir, f)).mtimeMs}`).join("|")
    + `|remotion:${require("remotion/package.json").version}`;
}

async function ensureBundle() {
  const stamp = sourceStamp();
  try {
    if (fs.existsSync(path.join(bundleDir, "index.html")) && JSON.parse(fs.readFileSync(stampFile, "utf8")).stamp === stamp) return bundleDir;
  } catch { /* rebuild */ }
  log("PHASE bundle");
  fs.rmSync(bundleDir, { recursive: true, force: true });
  fs.mkdirSync(cacheDir, { recursive: true });
  const out = await bundle({
    entryPoint: path.join(srcDir, "index.ts"),
    outDir: bundleDir,
    onProgress: (p) => { if (p % 25 === 0) log(`BUNDLE ${p}`); },
  });
  fs.writeFileSync(stampFile, JSON.stringify({ stamp, at: Date.now() }));
  return out;
}

const MIME = { ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
               ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg" };

/**
 * A port free on both IPv4 and IPv6 for Remotion's own bundle server. Remotion picks 3000 when 127.0.0.1:3000 is free
 * and then opens http://localhost:3000 — which the browser may resolve to ::1, where another app can be listening
 * (seen 1/11: the "TikTok Live Games" server on [::]:3000 answered, and the render died "getStaticCompositions").
 */
function freePort() {
  return new Promise((resolve) => {
    const s = http.createServer();
    s.once("error", () => {
      const v4 = http.createServer();
      v4.once("error", () => resolve(null));
      v4.listen(0, "127.0.0.1", () => { const p = v4.address().port; v4.close(() => resolve(p)); });
    });
    s.listen({ port: 0, host: "::", ipv6Only: false }, () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}

/** Serve the input video (and the mascot sticker) with Range support on 127.0.0.1:<random port>. */
function serveFile(file, extra = {}) {
  const server = http.createServer((req, res) => {
    const name = (req.url || "").split("?")[0];
    const target = name === "/input.mp4" ? file : extra[name];
    if (!target) { res.writeHead(404); res.end(); return; }
    const size = fs.statSync(target).size;
    const type = MIME[path.extname(target).toLowerCase()] || "application/octet-stream";
    const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range || "");
    let start = 0, end = size - 1;
    if (range) {
      if (range[1]) start = Number(range[1]);
      if (range[2]) end = Number(range[2]);
      if (!range[1] && range[2]) { start = Math.max(0, size - Number(range[2])); end = size - 1; }
      end = Math.min(end, size - 1);
    }
    if (start > end || start >= size) { res.writeHead(416, { "Content-Range": `bytes */${size}` }); res.end(); return; }
    res.writeHead(range ? 206 : 200, {
      "Content-Type": type, "Accept-Ranges": "bytes", "Content-Length": end - start + 1,
      ...(range ? { "Content-Range": `bytes ${start}-${end}/${size}` } : {}),
    });
    if (req.method === "HEAD") { res.end(); return; }
    fs.createReadStream(target, { start, end }).pipe(res);
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const base = `http://127.0.0.1:${server.address().port}`;
      resolve({ server, url: `${base}/input.mp4`, base });
    });
  });
}

/** `node render.mjs --prepare`: download the browser and build the bundle, render nothing (the Remotion add-on's install check). */
async function prepare() {
  log("PHASE browser");
  await ensureBrowser({ onBrowserDownload: () => ({ onProgress: ({ percent }) => log(`BROWSER ${Math.round(percent * 100)}`) }) });
  await ensureBundle();
  log("DONE");
}

async function main() {
  if (process.argv[2] === "--prepare") return prepare();
  const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  if (!spec.src || !fs.existsSync(spec.src)) throw new Error(`input video missing: ${spec.src}`);
  log("PHASE browser");
  await ensureBrowser({ onBrowserDownload: () => ({ onProgress: ({ percent }) => log(`BROWSER ${Math.round(percent * 100)}`) }) });
  const serveUrl = await ensureBundle();
  const extra = {};
  if (spec.mascot_file && fs.existsSync(spec.mascot_file)) extra[`/mascot${path.extname(spec.mascot_file).toLowerCase()}`] = spec.mascot_file;
  if (spec.frame_bg_file && fs.existsSync(spec.frame_bg_file)) extra[`/framebg${path.extname(spec.frame_bg_file).toLowerCase()}`] = spec.frame_bg_file;
  // the output format's uploaded background picture / video
  if (spec.canvas_bg_file && fs.existsSync(spec.canvas_bg_file)) extra[`/canvasbg${path.extname(spec.canvas_bg_file).toLowerCase()}`] = spec.canvas_bg_file;
  // the sound effects of the key moments: one served path per file (props.sfx[i] ↔ spec.sfx_files[i])
  const sfxPaths = (spec.sfx_files || []).map((f, i) => {
    if (!f || !fs.existsSync(f)) return null;
    const p = `/sfx${i}${path.extname(f).toLowerCase()}`;
    extra[p] = f;
    return p;
  });
  const { server, url, base } = await serveFile(spec.src, extra);
  try {
    const mascotPath = Object.keys(extra).find((k) => k.startsWith("/mascot"));
    const bgPath = Object.keys(extra).find((k) => k.startsWith("/framebg"));
    const canvasBgPath = Object.keys(extra).find((k) => k.startsWith("/canvasbg"));
    const props = spec.props || {};
    const sfx = (props.sfx || []).map((s, i) => (sfxPaths[i] ? { ...s, src: `${base}${sfxPaths[i]}` } : s));
    const inputProps = { ...props, sfx, src: url, ...(mascotPath ? { mascotSrc: `${base}${mascotPath}` } : {}),
                         ...(bgPath ? { frameBgSrc: `${base}${bgPath}` } : {}),
                         ...(canvasBgPath ? { canvasBgSrc: `${base}${canvasBgPath}` } : {}) };
    log("PHASE select");
    const port = await freePort();
    const composition = await selectComposition({ serveUrl, id: spec.composition || "DubSubtitles", inputProps, port });
    log(`FRAMES ${composition.durationInFrames} ${composition.width}x${composition.height}@${composition.fps}`);
    let last = -1;
    await renderMedia({
      composition, serveUrl, inputProps, port,
      codec: "h264", audioCodec: "aac", crf: spec.crf ?? 18, x264Preset: "fast", pixelFormat: "yuv420p",
      outputLocation: spec.out,
      concurrency: spec.concurrency ?? null,
      onProgress: ({ progress }) => {
        const pct = Math.floor(progress * 100);
        if (pct !== last) { last = pct; log(`PROGRESS ${progress.toFixed(3)}`); }
      },
    });
    log("DONE");
  } finally {
    server.close();
  }
}

main().catch((err) => {
  log(`ERROR ${(err && err.message) || String(err)}`);
  process.exit(1);
});
