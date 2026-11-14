# STATUS — grab-to-dub-flow

- Phase: 7 Ship — releasing **2.1.3** (director: "deploy và update 1 bản tool mới nhất", 15/11).
- G1 passed 15/11: approach **B**. G2: "OK hết, làm luôn" → built through to G4 without more gates.
- Baseline run 15/11 (QC agent 8534, data `D:\dflow-qc`, test Chromium + extension copy 0.7.2 at `D:\dflow-qc\ext`, Douyin login in
  `D:\dflow-qc\chrome-profile` still valid): scan 28 s / 82 videos, 6 downloads 20 s all ok, 3 dubs 121 s. Findings in `02-prd.md`.
- Built and verified: see `04-plan.md`, `05-verify.md`, `06-review.md`, `07-ship.md`.
- Scripts (scratchpad `qc/`): `base1.js` (scan + download), `base2.js` (dub a batch), `now1.js` (one-click flow, 5 videos),
  `now2.js` (editor scope default, open a clip mid-batch).

## Demo
- QC agent on **http://127.0.0.1:8534** (login `akiragosho` / `Password@123`, data `D:\dflow-qc`), started from this session.
  Stop: the python process listening on 8534.

## Not verified
- A real Douyin refusal being retried (only simulated), ≥ 10 videos in one lot, "Dừng tất cả" / "↻ Thử lại" clicked in the UI,
  the installed app (WebView2), the director's own Chrome.
