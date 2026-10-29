"""Facebook posts for a Vietnamese affiliate seller ("Bài viết").

Two ways in, one call: a brief (form fields — post type, product, main idea,
tone, length, call to action, how many images) and/or a chat message that
asks for a new post or changes to the current draft. The LLM answers with a
short reply for the chat plus the whole post as JSON: title (internal),
body, hashtags and English prompts for the images the user asked for.

Written for engagement, not for ads: a hook on the first line, short lines,
a question that invites comments, the shop link left for the comments.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from flowboard.services.channels import channel_block, platform_style, primary_platform
from flowboard.services.llm import run_llm
from flowboard.services.llm.base import LLMError

logger = logging.getLogger(__name__)

#: key → (label shown in the form, what the writer should aim for)
POST_TYPES: dict[str, tuple[str, str]] = {
    "discussion": ("Hỏi ý kiến / bàn luận", "an open question or relatable dilemma about the product or its use that makes people comment their own opinion or experience"),
    "review": ("Review sản phẩm", "an honest first-person review: what it is, what stood out, one practical tip taken from the given facts (how to use / store / enjoy it), who it suits; never invent flaws or taste judgements the facts do not state"),
    "story": ("Kể chuyện trải nghiệm", "a short first-person story (a moment, a problem, how the product fitted in) that ends with a question"),
    "tips": ("Mẹo / hướng dẫn", "3-5 practical tips or steps around the product's use, easy to save and share"),
    "compare": ("So sánh / chọn lựa", "a fair comparison of options (sizes, flavours, versions, or vs. common alternatives) and asks readers which they'd pick"),
    "sale": ("Chốt đơn / khuyến mãi", "a clear offer post: benefit first, then price or deal only if given, urgency without lying, how to order"),
    "minigame": ("Minigame / giveaway", "a simple engagement game (comment to guess, tag a friend, vote with emoji) tied to the product; rules short and clear; never promise prizes the seller did not state"),
    "serial": ("Câu chuyện nhiều kỳ (tập tiếp theo)", "one episode of an ongoing story told in first person across several posts: pick up exactly where the previous episode stopped, move the story forward with one new development, and end on a hook that makes readers want the next episode"),
}
#: Kept for briefs saved before a series became its own yes/no (any kind can be a series); not offered in the form.
LEGACY_KINDS = frozenset({"serial"})
#: kinds whose episodes carry one plot forward; the others continue a theme (next tips, next comparison…)
NARRATIVE_KINDS = frozenset({"serial", "story"})
#: how many earlier episodes the writer gets to read (full text)
SERIES_CONTEXT_EPISODES = 3
TONES: dict[str, str] = {
    "friendly": "thân thiện, gần gũi như bạn bè",
    "funny": "hài hước, bắt trend nhẹ nhàng",
    "expert": "am hiểu, đáng tin, rõ ràng",
    "story": "kể chuyện, cảm xúc",
    "short": "ngắn gọn, đi thẳng vào ý",
}
LENGTHS: dict[str, str] = {
    "short": "40-70 words",
    "medium": "80-150 words",
    "long": "150-260 words",
}
#: The default is "none": a post simply to be read, no ask at the end.
CTAS: dict[str, str] = {
    "none": "no call to action: a post simply to be read — end on a natural closing line (a thought, a takeaway, a "
            "warm sign-off); do not ask readers to comment, inbox, share or buy",
    "comment": "invite readers to comment (answer the question / share their experience)",
    "inbox": "invite readers to inbox / comment 'ib' for details",
    "link": "say the shop link is in the first comment (do not put a URL in the body)",
    "share": "invite readers to share or tag a friend who needs it",
}
MAX_IMAGES = 4

# What makes a post travel (separate from the call to action). key → (label, instruction); "auto" = the writer picks.
HOOKS: dict[str, tuple[str, str]] = {
    "auto": ("AI tự chọn", ""),
    "question": ("Câu hỏi chạm đúng vấn đề", "open with a question the reader instantly answers in their head"),
    "surprise": ("Sự thật bất ngờ", "open with a surprising but TRUE fact or observation drawn from the given facts"),
    "pain": ("Nỗi khổ quen thuộc", "open with a familiar everyday frustration the audience lives with"),
    "number": ("Con số / “3 điều…”", "open with a number promise (e.g. '3 điều mình ước biết sớm hơn…') and deliver exactly that many points"),
    "story": ("Khoảnh khắc kể chuyện", "open in the middle of a small real-life moment (time, place, what happened)"),
    "contrarian": ("Ngược số đông", "open with a gentle, defensible opinion that goes against a common belief, then explain it"),
}
FORMATS: dict[str, tuple[str, str]] = {
    "auto": ("AI tự chọn", ""),
    "lines": ("Đoạn ngắn, xuống dòng nhiều", "short paragraphs of 1-2 lines with a blank line between them"),
    "list": ("Danh sách gạch đầu dòng", "the core as a scannable list, one emoji bullet per point"),
    "qa": ("Hỏi – đáp", "a few short question/answer pairs"),
    "before_after": ("Trước – sau", "a clear before / after contrast"),
}
#: Extra pushes for reach and interaction; any number may be on.
BOOSTS: dict[str, tuple[str, str]] = {
    "question_end": ("Kết bằng câu hỏi dễ trả lời", "close with ONE easy, specific question people can answer in a few words"),
    "choice": ("Cho chọn A hay B", "give readers a light A-or-B choice to pick in the comments"),
    "save": ("Đáng lưu lại", "make part of it a mini checklist / tip list worth saving, and say it is worth saving for later"),
    "open_loop": ("Giữ người đọc tới cuối", "tease something early that is only resolved near the end, so people read to the last line"),
    "relatable": ("Chạm nỗi niềm chung", "name a feeling or situation most readers share ('ai cũng từng…')"),
    "share": ("Đáng chia sẻ", "make it useful for someone the reader knows, so sharing feels natural (never beg for shares)"),
}
EMOJIS: dict[str, tuple[str, str]] = {
    "few": ("Ít emoji", "at most 2 emoji in the whole post"),
    "some": ("Vừa phải", "a few emoji as bullets or emphasis"),
    "many": ("Nhiều emoji", "lively, emoji on most lines"),
}

_SYSTEM = (
    "You write social posts (Facebook by default; the brief names the platform) in natural Vietnamese for a Vietnamese TikTok Shop / Shopee affiliate seller who wants "
    "engagement (comments, shares, reactions) on their page or in groups.\n"
    "Rules:\n"
    "- First line is a hook that stops the scroll (a question, a surprising fact, a relatable pain). Then short lines "
    "and blank lines between ideas; emoji sparingly as bullets or emphasis.\n"
    "- Write for the ONE page in the CHANNEL / PAGE block: its subject, audience and voice. Each page is separate — "
    "never blend in another subject, audience or life situation the page is not about; a brief note (main idea, "
    "audience, image wishes) that does not fit this page is dropped, not merged in.\n"
    "- Sound like a real person (xưng 'mình', gọi 'mọi người' / 'các bạn' / 'cả nhà'), not an ad. Use only facts "
    "given about the product; never invent prices, discounts, prizes, certifications or health / medical claims.\n"
    "- End the way the CALL TO ACTION line says — it may say there is none; then do not tack on an ask. Never put URLs "
    "in the body (the link goes in the first comment).\n"
    "- Reach: the first two lines decide whether people tap 'Xem thêm', so they must create curiosity without "
    "clickbait lies. Facebook demotes engagement bait ('comment CÓ', 'like nếu…', 'tag 3 người', 'share để nhận'), so "
    "invite interaction the natural way the REACH lines ask for, never with those phrases.\n"
    "- hashtags: 3-6 relevant Vietnamese/English hashtags without spaces, as a list of strings starting with '#'.\n"
    "- image_prompts: exactly the number of images requested (0 if none), each an ENGLISH prompt for a photorealistic "
    "image that fits the post (lifestyle / product scene, natural light, no text, no logos, no real people's faces "
    "that look like celebrities). If a product photo is used as reference, describe the product as it looks.\n"
    "- first_comment: when an AFFILIATE LINK is given, the first comment under the post — one short, warm Vietnamese "
    "sentence that points readers to the product (e.g. 'Dạ em gửi các mom tham khảo gối bầu ở đây nha 🥰') followed by "
    "the link exactly as given, on its own line; the body then says the link is in the first comment. Without an "
    "affiliate link: \"\".\n"
    "- reply: one or two short Vietnamese sentences to the user about what you wrote or changed; it must match the body.\n"
    "Output ONLY one JSON object: {\"reply\": str, \"title\": str (<= 60 chars, internal name), \"body\": str, "
    "\"hashtags\": [str], \"image_prompts\": [str], \"first_comment\": str} — no prose, no code fences."
)


class PostWriterError(RuntimeError):
    pass


def post_text_of(body: str, hashtags: Any) -> str:
    """The text as it is posted: body, blank line, hashtags (same as the
    frontend's ``postText``). ``hashtags`` is the stored string or a list."""
    tags = " ".join(hashtags) if isinstance(hashtags, list) else str(hashtags or "")
    tags = tags.strip()
    return f"{(body or '').strip()}\n\n{tags}" if tags else (body or "").strip()


def _product_block(product: Optional[dict]) -> str:
    if not product:
        return ""
    lines = [f"PRODUCT: {product.get('name') or ''}"]
    for key, label in (("price", "Price"), ("description", "Looks (English)"), ("selling_points", "Selling points"),
                       ("shop", "Shop"), ("notes", "More facts")):
        if product.get(key):
            lines.append(f"{label}: {product[key]}")
    if product.get("aff_link"):
        lines.append(f"AFFILIATE LINK (goes ONLY in first_comment, never in the body): {product['aff_link']}")
    return "\n".join(lines)


def _clip_block(clip: Optional[dict]) -> str:
    if not clip:
        return ""
    lines = [f"THIS POST ACCOMPANIES A SHORT VIDEO: {clip.get('name') or ''}"]
    voice = [v for v in clip.get("lines") or [] if v]
    if voice:
        lines.append("Video voice-over: " + " / ".join(voice))
    return "\n".join(lines)


def _series_block(series: Optional[dict], kind: Optional[str] = None) -> str:
    """``series = {name, episode, previous: [{episode, title, body}]}`` — the
    story so far, so the new post continues it instead of restarting.
    ``kind`` is the post type every episode is written as: a story moves one
    plot forward; tips, reviews, comparisons… continue the series' theme."""
    if not series or not series.get("name"):
        return ""
    n = int(series.get("episode") or 1)
    prev = list(series.get("previous") or [])
    narrative = not kind or kind in NARRATIVE_KINDS
    lines = [f"STORY SERIES (Câu chuyện nhiều kỳ): \"{series['name']}\" — you are writing EPISODE {n}.",
             "This series belongs to THIS page only (the CHANNEL / PAGE block). Its subject is the series name and what the "
             "earlier episodes are about — stay on it, with the same narrator, people, setting and voice. Never bring in a "
             "subject, people, life situation or product that neither the earlier episodes nor this page are about. When the "
             "seller's notes (main idea, audience, image wishes) pull toward another subject, keep the series' subject and use "
             "only the part of the notes that fits it. The image prompts show this episode's subject too."]
    if not narrative and kind in POST_TYPES:
        lines.append(f"Every episode is a '{POST_TYPES[kind][0]}' post: write this episode in that POST TYPE. The series is the "
                     "thread linking the episodes (same narrator, the same people and situation, the same voice), never a reason "
                     "to drop the post type.")
    new_part = "one new development" if narrative else "new content (the next tips / points / options — never ones an earlier episode gave)"
    if not prev:
        lines.append("This is the first episode: " + ("set the scene and the people" if narrative else "set up who is talking and what the series is about")
                     + ", give it a reason to follow, end on a hook for the next episode. Open with 'Tập 1' or an equivalent marker.")
    else:
        lines.append("Earlier episodes (oldest first; the last one is where the series currently stands):")
        for p in prev[-SERIES_CONTEXT_EPISODES:]:
            body = re.sub(r"\s+", " ", str(p.get("body") or "")).strip()[:900]
            lines.append(f"- Tập {p.get('episode')}: {body}")
        lines.append(f"Rules for episode {n}: start with a one-line recap for new readers (\"Tiếp tục câu chuyện lần trước…\" / "
                     "\"Tập trước mình kể…\"), pick up the thread the last episode's ending left open, keep names, facts, "
                     f"subject and tone consistent with the earlier episodes, do NOT repeat them, add {new_part}, end on a hook "
                     f"for episode {n + 1}. Mark it 'Tập {n}'. If an earlier episode brought in something that does not belong "
                     "to this page's subject (CHANNEL / PAGE) or to the series name — a life situation, people, a pregnancy, a "
                     "product of another page — that was a mistake: do not follow the drift, leave it out of this episode and of "
                     "its image prompts, and continue the subject the series was built on.")
    return "\n".join(lines)


#: "Đăng dạng: 🎬 Reel" — the text is a Reel caption, not a feed post (wins over Length / Layout)
REEL_CAPTION = ("REEL CAPTION (wins over Length and Layout below): this text is the caption of a Facebook REEL — shown in two lines "
                "over a full-screen vertical video, the rest behind \"…xem thêm\". Write 1–3 short lines (under ~220 characters in all): "
                "a first line that makes people keep watching / tap \"xem thêm\", one line of the key point, then the call to action if "
                "one is asked; no headings, no lists, no long story — the video tells it. Hashtags as usual (3–6). The title stays short.")


def _brief_block(brief: dict, platform: str) -> str:
    kind = brief.get("kind") if brief.get("kind") in POST_TYPES else "discussion"
    out = [f"POST TYPE: {POST_TYPES[kind][0]} — {POST_TYPES[kind][1]}",
           f"PLATFORM FORMAT (wins over the length below when they conflict): {platform_style(platform)}"]
    if brief.get("fb_format") == "reel":
        # the post goes out as a Facebook Reel: its text is the Reel's caption, read under a full-screen video
        out.append(REEL_CAPTION)
    if brief.get("topic"):
        out.append(f"Main idea from the seller: {str(brief['topic'])[:600]}")
    if brief.get("audience"):
        out.append(f"Audience: {str(brief['audience'])[:200]}")
    out.append(f"Tone: {TONES.get(brief.get('tone') or 'friendly', TONES['friendly'])}")
    out.append(f"Length: {LENGTHS.get(brief.get('length') or 'medium', LENGTHS['medium'])}")
    out.append(f"CALL TO ACTION: {CTAS.get(brief.get('cta') or 'none', CTAS['none'])}")
    if (hook := HOOKS.get(brief.get("hook") or "auto")) and hook[1]:
        out.append(f"Opening line: {hook[1]}")
    if (fmt := FORMATS.get(brief.get("format") or "auto")) and fmt[1]:
        out.append(f"Layout: {fmt[1]}")
    out.append(f"Emoji: {EMOJIS.get(brief.get('emoji') or 'some', EMOJIS['some'])[1]}")
    boosts = [BOOSTS[b][1] for b in (brief.get("boosts") or []) if b in BOOSTS]
    if boosts:
        out.append("REACH (do all of these): " + "; ".join(boosts))
    n = _image_count(brief)
    out.append(f"Images requested: {n}" + (f" — wishes (take only what fits this page and this post's subject, e.g. the style; "
                                           f"drop people or subjects of another page): {str(brief.get('image_wish'))[:300]}"
                                           if n and brief.get("image_wish") else ""))
    return "\n".join(out)


def _image_count(brief: dict) -> int:
    try:
        return max(0, min(MAX_IMAGES, int(brief.get("images") or 0)))
    except (TypeError, ValueError):
        return 0


def _parse(text: str, n_images: int) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise PostWriterError("no JSON object in the answer")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise PostWriterError(f"bad JSON: {exc}") from exc
    body = str(data.get("body") or "").strip()
    if not body:
        raise PostWriterError("empty post")
    tags = data.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    hashtags = []
    for t in tags:
        t = "#" + re.sub(r"[\s#]+", "", str(t))
        if len(t) > 1 and t not in hashtags:
            hashtags.append(t)
    prompts = [str(p).strip() for p in (data.get("image_prompts") or []) if str(p).strip()][:n_images]
    return {
        "reply": str(data.get("reply") or "").strip(),
        "title": str(data.get("title") or "").strip()[:80],
        "body": body,
        "hashtags": hashtags[:8],
        "image_prompts": prompts,
        "first_comment": str(data.get("first_comment") or "").strip()[:600],
    }


_REVISE_IMAGE_SYSTEM = (
    "You rewrite ONE English image-generation prompt for a Facebook post picture. You get the CURRENT PROMPT and the "
    "USER'S CHANGE REQUEST (Vietnamese, possibly rough). Return the rewritten prompt only — one paragraph of plain "
    "English, no quotes, no explanation, <= 600 characters. Keep everything the user did not ask to change (subject, "
    "product, setting, style, 'no text, no logos'). Apply the request faithfully; if it names a product, keep the "
    "product's description verbatim. Photorealistic unless the current prompt says otherwise."
)


async def revise_image_prompt(current: str, request: str, *, timeout: float = 60.0) -> str:
    """``current`` (an image prompt of a post) rewritten to honour ``request``."""
    request = (request or "").strip()
    if not request:
        raise PostWriterError("Bạn chưa nói muốn ảnh khác thế nào.")
    user = f"CURRENT PROMPT:\n{(current or '').strip() or '(none)'}\n\nUSER'S CHANGE REQUEST:\n{request}"
    try:
        text = await run_llm("auto_prompt", user, system_prompt=_REVISE_IMAGE_SYSTEM, timeout=timeout)
    except LLMError as exc:
        raise PostWriterError(f"AI không sửa được prompt: {exc}") from exc
    text = (text or "").strip().strip('"').strip("'").strip()
    if not text:
        raise PostWriterError("AI trả về prompt rỗng.")
    return text[:600]


async def write_post(brief: dict, *, product: Optional[dict] = None, clip: Optional[dict] = None,
                     channel: Optional[dict] = None, series: Optional[dict] = None, current: Optional[dict] = None,
                     message: Optional[str] = None, history: Optional[list[dict]] = None,
                     extra: Optional[str] = None, timeout: float = 120.0) -> dict[str, Any]:
    """A new post from ``brief``, or ``current`` revised per ``message``.
    ``history`` is the chat so far (``[{role: user|assistant, text}]``).
    ``channel`` (with its brainstorm) sets the platform format and the
    direction the post must follow. ``extra`` is one more block for the
    prompt (e.g. the structure of a viral post to follow)."""
    brief = brief or {}
    if series and series.get("name") and not brief.get("kind"):
        brief = {**brief, "kind": "serial"}
    platform = brief.get("platform") or primary_platform(channel)
    parts = [_brief_block(brief, platform)]
    if (sb := _series_block(series, brief.get("kind"))):
        parts.append(sb)
    if (chb := channel_block(channel)):
        parts.append(chb)
    if (pb := _product_block(product)):
        parts.append(pb)
    if (cb := _clip_block(clip)):
        parts.append(cb)
    if extra and extra.strip():
        parts.append(extra.strip()[:4000])
    if history:
        convo = "\n".join(f"{'SELLER' if h.get('role') == 'user' else 'YOU'}: {str(h.get('text') or '')[:500]}"
                          for h in history[-8:])
        parts.append(f"CHAT SO FAR:\n{convo}")
    if current and str(current.get("body") or "").strip():
        parts.append("CURRENT DRAFT (revise it; keep what the seller did not ask to change):\n"
                     + json.dumps({k: current.get(k) for k in ("title", "body", "hashtags", "image_prompts")},
                                  ensure_ascii=False))
    if message and message.strip():
        parts.append(f"SELLER'S MESSAGE NOW: {message.strip()[:1000]}")
    else:
        parts.append("Write the post now.")
    try:
        text = await run_llm("auto_prompt", "\n\n".join(parts), system_prompt=_SYSTEM, timeout=timeout)
    except LLMError as exc:
        raise PostWriterError(f"LLM failed: {exc}") from exc
    # In chat the seller may ask for images in the message itself ("thêm 2 ảnh").
    cap = MAX_IMAGES if (message and message.strip()) else _image_count(brief or {})
    post = _parse(text, cap)
    # Revisions about the text tend to come back without the image prompts;
    # keep the draft's unless the seller talked about images.
    aff = str((product or {}).get("aff_link") or "").strip()
    if aff and aff not in post["first_comment"]:
        post["first_comment"] = (post["first_comment"] + "\n" + aff).strip() if post["first_comment"] else f"Link sản phẩm em để đây nha 🥰\n{aff}"
    if not aff:  # no link to give → nothing the model invents goes in the first comment
        post["first_comment"] = str((current or {}).get("first_comment") or "")
    kept = [str(p) for p in (current or {}).get("image_prompts") or [] if str(p).strip()]
    if kept and not post["image_prompts"] and not _IMAGE_WORDS.search(message or ""):
        post["image_prompts"] = kept[:MAX_IMAGES]
    return post


_IMAGE_WORDS = re.compile(r"ảnh|hình|image|photo", re.I)
