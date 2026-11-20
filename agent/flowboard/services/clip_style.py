"""How a DFlow ad clip should look and sound: like a real buyer filmed it on
a phone, not like an ad shoot (7/11).

The first templates were written as a studio commercial — "editorial photo",
"soft even studio lighting", "locked-off camera", the model holding a pose
and smiling into the lens, a seller reading the spec sheet — and the clips
came out stiff ("máy móc quá"). These rules come from the UGC prompting
guides for Veo / Flow (Google's Veo 3.1 guide: cinematography + subject +
action + context + style, audio as its own line; the UGC prompt packs: a
named phone position, one main action per clip plus one human detail, a
lived-in place, a named light source, real texture, the person busy with the
product rather than presenting it, words like "cinematic" / "flawless" push
the model to plastic). Every LLM that writes scene prompts reads them: the
template tailoring (``script_tailor``), the product-link plan
(``product_link``) and the reference-video plan (``reference_video``).

``voiceless`` clips ("🔇 Không lời") have no voice-over and no subtitles:
the pictures and the real sounds of the moment carry the clip.
"""
from __future__ import annotations

import re

#: Added to every image prompt the scene writers make: "phone footage" made Nano Banana draw the camera app itself
#: (18/11, clip #155 scene 4: a status bar with the time and a red record button over the picture).
NO_PHONE_UI = "No phone screen, camera-app interface, record button or status bar in the picture."

LOOK_RULES = (
    "LOOK — a real buyer filmed it on a phone, not an ad shoot:\n"
    "- Vertical 9:16 smartphone footage. Say where the phone is: held by a friend at chest height, propped on "
    "a shelf / dashboard / against a mug, or a mirror selfie (the phone in hand covers part of the face). One "
    "framing per scene: waist-up, medium, or a close detail of hands and product.\n"
    "- A real, lived-in place where a buyer would actually use THIS product (a cooling work jacket → outdoors in "
    "hard sun at a worksite or on a motorbike; skincare → a bathroom mirror at night; a snack → a desk or a sofa; a "
    "kitchen tool → a home kitchen counter). Add one or two ordinary details of that place (a charger cable, a "
    "towel, a helmet, a half-finished iced coffee). Scenes that share a place keep the same place.\n"
    "- Name the light that is really there: window daylight from one side, harsh noon sun, a warm evening lamp, "
    "the glow of a screen. Slight shadows are fine.\n"
    "- Real texture: fabric weave and creases, natural skin with pores and a little shine, everyday hair, little "
    "or no makeup, normal clothes, surfaces with some wear.\n"
    "- Never use the words editorial, studio, cinematic, commercial, luxury, flawless, perfect, beauty shot, glossy, "
    "pristine, hero shot, magazine, lookbook, and no empty space kept for a logo or text. No on-screen text.\n"
    "- The image is what the phone's camera SEES, never a picture of a phone screen: no camera-app interface, "
    "record button, status bar, clock or battery icon, no phone frame around the picture.\n"
    "- ONE item in every scene: the product shows the same colour, pattern and details in every scene, as in the "
    "seller's reference photo. Never take its colour from a list of colour options / variants in the description "
    "or notes (a bag sold in cream, red and pink is the one in the photo). Not sure of the colour: name no colour "
    "and write 'the <item> from the reference photo'.\n"
)

MOTION_RULES = (
    "MOTION (video_prompt; the scene image is animated into an 8-second clip):\n"
    "- Keep the '0-3s: … 3-6s: … 6-8s: …' timeline. ONE main action carried through the clip the way a person "
    "really does it (puts it on and zips it up, takes a sip, presses the button and waits, tugs the hem and checks "
    "the mirror), plus ONE small human detail (a glance down at the product, a little exhale, pushing hair aside, a "
    "quick look off-camera, a closed-mouth laugh).\n"
    "- People look at the product, the mirror or what they are doing; at most a short glance at the lens. Never "
    "'holds the pose', 'smiles at the camera', thumbs-up, pointing or waving at the camera, presenting.\n"
    "- Real physics: weight shifts, fabric moves and settles, hands press and grip, natural starts and stops. "
    "Everything at real-time speed: never 'slow', 'slowly' or 'slow motion' (Veo then renders slow motion, which "
    "looks choppy at 24 fps).\n"
    "- Camera: a handheld phone with subtle natural micro-shake and one small reframe, or a propped phone that "
    "stays still. Never locked-off, dolly, crane, orbit, slow motion or several camera moves.\n"
    "- End with 'Audio: ' and one or two real sounds of that moment (zipper, fabric rustle, a fan's soft whirr, "
    "street traffic, a sizzle, a cap click, keyboard taps). Mouths stay closed — nobody speaks.\n"
)

#: Spoken Vietnamese voice-over, read by a TTS voice over the clip.
VOICE_RULES = (
    "VOICE (voice, a Vietnamese voice-over read over the clip, at most {words} words):\n"
    "- Sound like a real buyer telling a friend, not a seller reading a spec sheet: xưng 'mình', short natural "
    "sentences, everyday words (nè, nha, luôn, thiệt, nói thật) — at most one such word per line.\n"
    "- Talk about what the picture shows right now and turn a fact into a feeling or a situation ('pin 8-14 tiếng' "
    "→ 'đi làm từ sáng tới chiều vẫn còn pin'). One idea per line; never list several features in one line, never "
    "catalogue phrases like 'chất liệu cao cấp', 'thiết kế hiện đại', 'sản phẩm'.\n"
    "- Line 1 hooks in the first two seconds: a relatable problem, a surprising detail or a blunt opinion. Do not "
    "open with 'Mọi người ơi, đây là…' or the full product name; call it naturally ('cái áo này', 'em quạt này') "
    "and say its real short name once somewhere in the clip.\n"
    "- The last line is a soft nudge to the cart that fits who it is for ('ai hay chạy ngoài nắng thì xem giỏ hàng "
    "nha'), not a hard sell.\n"
    "- Only facts that are given. Never invent a past ('mình xài ba tháng rồi'), results, reviews, prices or "
    "discounts; no health or medical promises. No hashtags, emoji or quotation marks.\n"
)

#: "🔇 Không lời": no voice-over, no subtitles.
VOICELESS_RULES = (
    "NO VOICE — this clip has no voice-over and no subtitles; the pictures and the real sounds tell everything:\n"
    "- Return an empty voice (\"\") for every scene.\n"
    "- Make a small story a viewer follows with the sound off: the situation (why it is needed) → putting it on / "
    "taking it out → the product doing its job in real use → a quiet satisfied ending (an easy exhale, walking off, "
    "a last check in the mirror). Each scene one clear, satisfying action, the product big and easy to read; vary "
    "the framing between scenes (waist-up, a close detail of the hands on the feature, the product in use).\n"
    "- The 'Audio: ' line matters most here: one or two crisp real sounds that sell the moment (a zip, a click, "
    "fabric swish, a fan's whirr, a crunch, a pour) over quiet room tone. No music, no speech.\n"
)


def voice_rules(words: int) -> str:
    return VOICE_RULES.format(words=words)


def scene_rules(*, voiceless: bool, words: int) -> str:
    """The look + motion rules and either the voice-over or the no-voice rules."""
    return LOOK_RULES + MOTION_RULES + (VOICELESS_RULES if voiceless else voice_rules(words))


_NATIONALITY = {"vn": "Vietnamese", "kr": "Korean", "jp": "Japanese", "cn": "Chinese",
                "th": "Thai", "us": "American", "fr": "French"}


def person_line(gender: str | None, country: str | None = None) -> str:
    """Who is in the shots, for the LLM — so a male model is never written as
    "she" (clip #68 7/11: "she slowly turns her shoulder" on a man)."""
    who = _NATIONALITY.get(country or "", "")
    if gender in ("hands_female", "hands_male"):
        kind = "female" if gender == "hands_female" else "male"
        return f"PERSON: only {who + ' ' if who else ''}{kind} hands and forearms appear, never a face."
    if gender == "male":
        return f"PERSON: the model is a {who + ' ' if who else ''}man — write he / his / him."
    if gender == "female":
        return f"PERSON: the model is a {who + ' ' if who else ''}woman — write she / her."
    if gender == "none":
        return "PERSON: nobody appears; only the product (and its surroundings)."
    return ""


#: Polishing words the rules above forbid (lower case). Used by the tests to
#: keep the templates honest, and by :func:`polish_words` for a quick check.
POLISH_WORDS = ("editorial", "studio", "cinematic", "commercial", "luxury", "flawless", "beauty shot",
                "pristine", "hero shot", "magazine", "lookbook", "locked-off", "for a logo", "for text",
                "for a price")


def polish_words(text: str) -> list[str]:
    low = (text or "").lower()
    return [w for w in POLISH_WORDS if re.search(r"\b" + re.escape(w) + r"\b", low)]


#: The how-to line of a clip's script note, with and without a voice.
NOTE_VOICE = ("Lồng tiếng: mỗi cảnh có sẵn một câu thoại tiếng Việt (sửa ở bước 2); bước 5 đọc giọng + phụ đề rồi "
              "ghép thành clip hoàn chỉnh.")
NOTE_VOICELESS = ("🔇 Clip không lời: không lồng tiếng, không phụ đề — giữ âm thanh thật của từng video (tiếng vải, "
                  "tiếng máy, tiếng xung quanh); bước 5 ghép lại, thêm nhạc nền nếu muốn.")
