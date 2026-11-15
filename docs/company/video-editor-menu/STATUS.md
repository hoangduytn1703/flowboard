# STATUS — video-editor-menu
- Phase: 4-5 done for slice 1 (15/11); demo handed to the director. G2+G3 approved 15/11 ("làm như đề xuất").
- Decisions: approach B; trimming the old forms deferred until the director has tried the new menu; local imports are
  not transcribed until subtitles are asked for; menu shown to plans with dub or cut; "Bỏ khỏi danh sách" removes the row only;
  AI assistant hidden for everyone and taken out of the Premium plan.
- Done: backend (video_edit, routes/edit), EditPage, hear-on-demand in the editor, the other pages send videos here,
  old links redirect, tests (test_video_edit 4), tsc, Playwright on the QC agent.
- Demo: http://127.0.0.1:8534 (QC agent started by Claude, data D:/dflow-qc, login akiragosho / the seed password). Stop: kill the PID listening on 8534.
- Not committed. Next: director tries it → then decide what to trim in the Lồng tiếng / Cắt / Cào kênh forms; release.
