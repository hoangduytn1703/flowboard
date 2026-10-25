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
CTAS: dict[str, str] = {
    "comment": "invite readers to comment (answer the question / share their experience)",
    "inbox": "invite readers to inbox / comment 'ib' for details",
    "link": "say the shop link is in the first comment (do not put a URL in the body)",
    "share": "invite readers to share or tag a friend who needs it",
}
MAX_IMAGES = 4

_SYSTEM = (
    "You write social posts (Facebook by default; the brief names the platform) in natural Vietnamese for a Vietnamese TikTok Shop / Shopee affiliate seller who wants "
    "engagement (comments, shares, reactions) on their page or in groups.\n"
    "Rules:\n"
    "- First line is a hook that stops the scroll (a question, a surprising fact, a relatable pain). Then short lines "
    "and blank lines between ideas; emoji sparingly as bullets or emphasis.\n"
    "- Sound like a real person (xưng 'mình', gọi 'mọi người' / 'các bạn' / 'cả nhà'), not an ad. Use only facts "
    "given about the product; never invent prices, discounts, prizes, certifications or health / medical claims.\n"
    "- End with the requested call to action; posts aimed at engagement end with a question. Never put URLs in the "
    "body (the link goes in the first comment).\n"
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


def _series_block(series: Optional[dict]) -> str:
    """``series = {name, episode, previous: [{episode, title, body}]}`` — the
    story so far, so the new post continues it instead of restarting."""
    if not series or not series.get("name"):
        return ""
    n = int(series.get("episode") or 1)
    prev = list(series.get("previous") or [])
    lines = [f"STORY SERIES: \"{series['name']}\" — you are writing EPISODE {n}."]
    if not prev:
        lines.append("This is the first episode: set the scene and the people, give it a reason to follow, end on a hook. "
                     "Open with 'Tập 1' or an equivalent marker.")
    else:
        lines.append("Earlier episodes (oldest first; the last one is where the story currently stands):")
        for p in prev[-SERIES_CONTEXT_EPISODES:]:
            body = re.sub(r"\s+", " ", str(p.get("body") or "")).strip()[:900]
            lines.append(f"- Tập {p.get('episode')}: {body}")
        lines.append(f"Rules for episode {n}: start with a one-line recap for new readers (\"Tiếp tục câu chuyện lần trước…\" / "
                     "\"Tập trước mình kể…\"), keep names, facts and tone consistent with the earlier episodes, do NOT repeat "
                     f"them, add one new development, end on a hook for episode {n + 1}. Mark it 'Tập {n}'.")
    return "\n".join(lines)


def _brief_block(brief: dict, platform: str) -> str:
    kind = brief.get("kind") if brief.get("kind") in POST_TYPES else "discussion"
    out = [f"POST TYPE: {POST_TYPES[kind][0]} — {POST_TYPES[kind][1]}",
           f"PLATFORM FORMAT (wins over the length below when they conflict): {platform_style(platform)}"]
    if brief.get("topic"):
        out.append(f"Main idea from the seller: {str(brief['topic'])[:600]}")
    if brief.get("audience"):
        out.append(f"Audience: {str(brief['audience'])[:200]}")
    out.append(f"Tone: {TONES.get(brief.get('tone') or 'friendly', TONES['friendly'])}")
    out.append(f"Length: {LENGTHS.get(brief.get('length') or 'medium', LENGTHS['medium'])}")
    out.append(f"Call to action: {CTAS.get(brief.get('cta') or 'comment', CTAS['comment'])}")
    n = _image_count(brief)
    out.append(f"Images requested: {n}" + (f" — wishes: {str(brief.get('image_wish'))[:300]}" if n and brief.get("image_wish") else ""))
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
                     timeout: float = 120.0) -> dict[str, Any]:
    """A new post from ``brief``, or ``current`` revised per ``message``.
    ``history`` is the chat so far (``[{role: user|assistant, text}]``).
    ``channel`` (with its brainstorm) sets the platform format and the
    direction the post must follow."""
    brief = brief or {}
    if series and series.get("name") and not brief.get("kind"):
        brief = {**brief, "kind": "serial"}
    platform = brief.get("platform") or primary_platform(channel)
    parts = [_brief_block(brief, platform)]
    if (sb := _series_block(series)):
        parts.append(sb)
    if (chb := channel_block(channel)):
        parts.append(chb)
    if (pb := _product_block(product)):
        parts.append(pb)
    if (cb := _clip_block(clip)):
        parts.append(cb)
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
