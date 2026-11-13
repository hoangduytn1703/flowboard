from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel, Column, JSON

from flowboard.db.paths import StoragePath


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


#: AppSetting key holding the dashboard-set Google Flow project id.
#: Named once here so the resolver, the routes and the tests cannot drift
#: apart over a string literal.
FLOW_PROJECT_SETTING_KEY = "flow_project_id"


class AppSetting(SQLModel, table=True):
    """Runtime-settable configuration, one row per key.

    Exists because the pinned Flow project had nowhere durable to live but
    ``FLOWBOARD_FLOW_PROJECT_ID``, which ``config`` reads once at import —
    so changing which project Flowboard generates into meant editing ``.env``
    and restarting the agent.

    Values are plain strings. There is one setting today, and a typed column
    per setting would make every future knob a schema migration; parsing at
    the edge that cares is cheaper.
    """
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=_utcnow)


class Board(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    # Free-form board settings. The Quicktool wizard keeps its state here
    # (``quicktool``: template, product, current step, auto-run flag) so a
    # clip reopens where the user left it.
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)


class Node(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    board_id: int = Field(foreign_key="board.id", index=True)
    short_id: str = Field(index=True)
    type: str
    x: float = 0.0
    y: float = 0.0
    w: float = 240.0
    h: float = 160.0
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "idle"
    created_at: datetime = Field(default_factory=_utcnow)


class Edge(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    board_id: int = Field(foreign_key="board.id", index=True)
    source_id: int = Field(foreign_key="node.id")
    target_id: int = Field(foreign_key="node.id")
    kind: str = "ref"
    # Per-edge variant pin: when the source node holds multiple variants
    # (`data.mediaIds`), this index selects WHICH variant feeds the
    # downstream as a reference. None = "fall back to the source's
    # active mediaId" (the natural single-variant case).
    #
    # Why per-edge instead of expanding all variants on the wire: each
    # variant of the same upstream produces a SEPARATE Flow API call
    # (Flow doesn't bind output[i] to input[i] when both are
    # multi-variant). Pinning lets the user say "use variant 2 for
    # downstream A, variant 3 for downstream B" with two clicks; the
    # edge UI surfaces the pinned index so the binding stays visible.
    source_variant_idx: Optional[int] = None


class Request(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    node_id: Optional[int] = Field(default=None, foreign_key="node.id", index=True)
    type: str
    params: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "queued"
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None


class Asset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # node_id is optional — assets can arrive from TRPC before any node
    # binding (e.g. the user browses an old Flow project).
    node_id: Optional[int] = Field(default=None, foreign_key="node.id", index=True)
    kind: str  # image | video | thumbnail
    # Media id (the hex uuid from Google Flow). Unique so ingest can upsert.
    uuid_media_id: Optional[str] = Field(default=None, index=True, unique=True)
    # Latest captured signed GCS URL (expires — refreshed when user reopens
    # Flow tab).
    url: Optional[str] = None
    # Stored relative to the account's data folder (``media/x.mp4``) so the
    # same row works on every machine; reads give an absolute path here.
    local_path: Optional[str] = Field(default=None, sa_column=Column(StoragePath()))
    mime: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)


class MediaProjectMapping(SQLModel, table=True):
    """Cross-project media re-upload cache.

    Flow scopes mediaIds to the project they were uploaded in — a
    ref_media_id from project A is unknown to project B even though we
    have the bytes cached locally. When a dispatch needs to reference
    media from another project (e.g. a cross-board Reference reused on
    a different board), we re-upload the bytes under the target project
    and record the (original, project) → project-local mapping here so
    subsequent dispatches skip the upload round-trip.

    Each row says: "bytes of `original_media_id` are also available
    under `project_id` as `project_local_media_id`". Unique on
    (original_media_id, project_id) — composite index in __table_args__.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    original_media_id: str = Field(index=True)
    project_id: str = Field(index=True)
    project_local_media_id: str
    created_at: datetime = Field(default_factory=_utcnow)
    __table_args__ = (
        UniqueConstraint(
            "original_media_id", "project_id",
            name="uq_media_project_mapping",
        ),
    )


class Reference(SQLModel, table=True):
    """User-curated saved media for cross-board reuse.

    Distinct from Asset (auto-managed cache index). Each Reference
    points at one media_id and snapshots enough metadata to spawn a
    brand-new visual_asset node in any board without re-vision or
    re-upload.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    # Not unique: a cloned model ("⧉ Nhân bản" on /models) shares the photo
    # of its original. ``db.ensure_reference_media_id_not_unique`` drops the
    # unique index of older DBs.
    media_id: str = Field(index=True)
    url: Optional[str] = None
    label: str = ""
    kind: str  # "image" | "character" | "visual_asset" | "storyboard_shot"
    ai_brief: Optional[str] = None
    aspect_ratio: Optional[str] = None
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    pinned: bool = False
    position: int = 0
    source_board_id: Optional[int] = Field(default=None, foreign_key="board.id", index=True)
    source_node_short_id: Optional[str] = None
    # Kind-specific extras. For ``character`` (the Quicktool model library):
    # gender / country / vibe / extras keys of the character builder, the
    # rendered prompt and the product name the model was made for — enough
    # to put a saved model back on a wizard board with its form filled in.
    # Added after the table shipped: ``db.ensure_reference_meta_column``
    # ALTERs it in on existing DBs.
    meta: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)


class SavedPrompt(SQLModel, table=True):
    """The Quicktool prompt library: a scene image prompt, a clip motion
    prompt or a voice line the user wants to reuse on another clip.
    Plain text, no media; ``create_all`` adds the table on first start."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(index=True)  # "image" | "video" | "narration"
    title: str = ""
    text: str
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    source_board_id: Optional[int] = Field(default=None, index=True)
    uses: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class Post(SQLModel, table=True):
    """A Facebook post written in "Bài viết" (or step 5 of a clip): text,
    hashtags, the image prompts the writer suggested and the images made
    from them (media ids). ``brief`` keeps the form the user filled in so
    the post can be rewritten later. ``create_all`` adds the table."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = ""  # post type key (services/post_writer.POST_TYPES)
    title: str = ""
    body: str = ""
    hashtags: str = ""
    # "Bình luận đầu tiên": the affiliate link with one friendly line, pasted
    # as the first comment under the post (links in the body hurt reach).
    first_comment: str = ""
    product_id: Optional[int] = Field(default=None, index=True)
    board_id: Optional[int] = Field(default=None, index=True)
    # The channel (page) the post is for; its brainstorm steers the writer.
    channel_id: Optional[int] = Field(default=None, index=True)
    # A multi-part story ("Câu chuyện nhiều kỳ"): posts sharing ``series`` are
    # its episodes; the writer reads the earlier ones to continue.
    series: str = Field(default="", index=True)
    episode: int = 0
    images: list = Field(default_factory=list, sa_column=Column(JSON))
    image_prompts: list = Field(default_factory=list, sa_column=Column(JSON))
    # A short Flow video (media id) posted instead of the images (a Facebook
    # post carries photos or one video, not both). ``db.ensure_post_video_column``.
    video: str = ""
    brief: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Channel(SQLModel, table=True):
    """A page / account the seller posts to ("Kênh"): where (platforms),
    what business, who for and what the page is meant to do. After the
    first few posts a brainstorm (``services/channels.brainstorm``) turns
    those posts into a direction — positioning, voice, content pillars,
    do / don't — that later posts follow. Posts link by ``Post.channel_id``,
    clips by ``board.data.quicktool.channel_id``. ``create_all`` adds the
    table."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    platforms: list = Field(default_factory=list, sa_column=Column(JSON))  # services/channels.PLATFORMS keys
    category: str = ""  # first of ``categories`` (kept for older readers)
    categories: list = Field(default_factory=list, sa_column=Column(JSON))  # up to 3 services/channels.CATEGORIES keys
    description: str = ""  # what the page sells / talks about, in the seller's words
    audience: str = ""
    goal: str = ""  # what posts should achieve: engagement, orders, followers…
    # The page itself (optional): read through the extension and reviewed by
    # the LLM (``services/channel_page``) — score, strengths, what to fix and
    # the style its real posts use, which the writer and brainstorm follow.
    link: str = ""
    page_review: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    brainstorm: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    # A connected Facebook Page (Graph API): the page's id and name. The page
    # access token itself lives in the central settings store, never here
    # (``services/facebook_publish``). Added after the table shipped:
    # ``db.ensure_channel_facebook_columns``.
    fb_page_id: str = ""
    fb_page_name: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Schedule(SQLModel, table=True):
    """One slot on the posting calendar ("Lịch đăng"): a saved post or a
    finished clip, on a channel, at a time. ``auto`` = publish through the
    channel's connected Facebook Page when the time comes (the scheduler
    loop in ``services/scheduler``); otherwise the slot only reminds, and
    the seller marks it posted. ``create_all`` adds the table."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(index=True)  # "post" | "clip"
    post_id: Optional[int] = Field(default=None, index=True)
    board_id: Optional[int] = Field(default=None, index=True)
    channel_id: Optional[int] = Field(default=None, index=True)
    scheduled_at: datetime = Field(index=True)  # UTC
    # planned → (due) → posted | failed | skipped. "due" is derived (planned and past).
    status: str = Field(default="planned", index=True)
    auto: bool = False
    # How a video goes out on Facebook: "post" (a feed post with the video) | "reel" (Reels, 3–90 s vertical).
    fb_format: str = Field(default="post")
    # "📲 Thêm vào tin": also put it on the Page's Story when it goes out (the video — its first 60 s — or the first photo)
    fb_story: bool = False
    note: str = ""
    # What publishing produced: the Facebook post id / permalink, or the error.
    result: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    posted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FbPost(SQLModel, table=True):
    """A post on a connected Facebook Page, read back by "🔄 Đồng bộ từ
    Facebook" (services/fb_sync). ``slot_id`` = the tool published it (a
    Schedule slot) — never listed twice; otherwise it went up by hand and
    shows on "Lịch đăng" as such. ``post_id`` = the saved post (Bài đã lưu)
    whose text it carries. ``create_all`` adds the table."""
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(index=True)
    fb_id: str = Field(index=True)  # "<page>_<post>"
    media_id: str = ""  # attachments.target.id: a Reel's / video's id, a photo's id
    created_time: datetime = Field(index=True)  # UTC, when it went out
    kind: str = ""  # status_type: added_photos | added_video | mobile_status_update…
    reel: bool = False
    message: str = ""
    permalink: str = ""
    picture: str = ""  # full_picture (a Facebook CDN URL; refreshed by every sync)
    slot_id: Optional[int] = None
    post_id: Optional[int] = Field(default=None, index=True)
    # read back each sync: views, viewers, clicks, reactions, comments, shares; a Reel adds plays, replays,
    # avg_watch_s, watch_time_s, followers, length_s, retention (41 points, % still watching over the video)
    stats: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    synced_at: datetime = Field(default_factory=_utcnow)
    __table_args__ = (UniqueConstraint("channel_id", "fb_id", name="uq_fbpost_channel_fb"),)


class AssistantMessage(SQLModel, table=True):
    """One message of the "🤖 Trợ lý AI" chat (services/assistant): the
    person's or the assistant's. ``data`` = what a reply shows besides its
    text (the task it started, a picture, a link). ``create_all`` adds it."""
    id: Optional[int] = Field(default=None, primary_key=True)
    role: str  # "user" | "assistant"
    text: str = ""
    data: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    task_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class AssistantTask(SQLModel, table=True):
    """Work the assistant runs in the background after a chat message
    ("create_model" today — whole clips are Phase A's next steps).
    ``state`` = how far it got (step, Flow request id, media / saved ids)
    so it carries on after the agent restarts."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str
    status: str = Field(default="running", index=True)  # running | done | error
    title: str = ""
    args: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    state: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class DecorPreset(SQLModel, table=True):
    """A frame or a dancing sticker the seller kept ("★ Lưu") for the dubbing
    editor (services/dub_decor): ``kind`` "frame" | "mascot", ``data`` the
    layout part as is (frame params incl. a background image media id, or
    the mascot spec). ``thumb`` = a media id to show in the list. ``create_all``
    adds the table."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    name: str = ""
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    thumb: str = ""
    uses: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class DubLink(SQLModel, table=True):
    """A link in the dubbing link library ("📚 Thư viện link"): every link found
    in a .txt / .md file the seller imported (services/dub_links). ``key`` is
    the canonical form (``douyin:<id>``, ``youtube:<id>``… or host + path) that
    matches it to dub jobs made from the same video, however it was written.
    ``queued`` = waiting in the library queue with the dub ``options`` picked
    when it was queued; the feeder starts it when the dub queue has room and
    keeps the ``job_id``. ``create_all`` adds the table."""
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str
    key: str = Field(index=True)
    label: str = ""
    source: str = ""
    position: int = 0
    queued: bool = False
    queued_at: Optional[datetime] = None
    options: dict = Field(default_factory=dict, sa_column=Column(JSON))
    job_id: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)

class Swipe(SQLModel, table=True):
    """A post or video that did well somewhere ("Mẫu đang hot"), kept with
    the LLM's breakdown of why — hook, structure, triggers — so the seller
    can write their own version for a product. ``create_all`` adds the table."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = "post"  # "post" | "video"
    url: str = ""
    platform: str = ""
    title: str = ""
    text: str = ""  # the captured caption / transcript
    analysis: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    # Our own posts / clips written from this swipe.
    uses: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class Product(SQLModel, table=True):
    """A product the user sells, saved once and reused across ad boards.

    Creating a board from a template with a product puts its photo on the
    template's ``product`` node and its description into every prompt, so
    the user does not re-upload and re-describe the same item per clip.

    ``media_ids`` are Flow media ids from ``/api/upload``, first = main
    photo. They belong to the project that was pinned at upload time; the
    bytes stay in the local media cache, which is what lets a dispatch into
    another project re-upload them (``media_project_sync``).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    # English phrase dropped into prompts as {{product}}, e.g. "a white
    # cotton t-shirt with a small red logo on the chest".
    description: str = ""
    category: str = "other"  # fashion | cosmetics | food | other
    price: str = ""
    # Vietnamese selling points, one per line — the script note and caption.
    selling_points: str = ""
    # Who it is for: male / female / unisex / "" (unknown) — the clip's model
    # must match a male / female product (services/product_gender.py).
    gender: str = ""
    link: str = ""
    # Affiliate: the tracked short link (s.shopee.vn/…, vt.tiktok.com/…) that
    # goes in a post's first comment, and the shop it belongs to. Unique per
    # link so the same product is not saved twice (routes/products).
    aff_link: str = ""
    shop: str = ""
    notes: str = ""
    media_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    aspect_ratio: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    board_id: int = Field(foreign_key="board.id", index=True)
    role: str  # user | assistant | system
    content: str
    mentions: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)


class ChatAttachment(SQLModel, table=True):
    """One uploaded image attached to a chat message.

    The bytes live at the linked Asset's ``local_path``
    (``storage/chat_uploads/``); the Asset row stays ``node_id=None``
    (unbound) until the agent binds it to a node.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: int = Field(foreign_key="chatmessage.id", index=True)
    asset_id: int = Field(foreign_key="asset.id", index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class ChatRun(SQLModel, table=True):
    """One server-side agent execution spawned from a chat message."""

    id: Optional[int] = Field(default=None, primary_key=True)
    board_id: int = Field(foreign_key="board.id", index=True)
    user_message_id: int = Field(foreign_key="chatmessage.id")
    status: str = "running"  # running | done | failed
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None


class Plan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    board_id: int = Field(foreign_key="board.id", index=True)
    spec: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "draft"  # draft | approved | running | done | failed
    created_at: datetime = Field(default_factory=_utcnow)


class PlanRevision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="plan.id", index=True)
    rev_no: int
    spec: dict = Field(default_factory=dict, sa_column=Column(JSON))
    edits: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)


class PipelineRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="plan.id", index=True)
    status: str = "pending"  # pending | running | done | failed
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


class BoardFlowProject(SQLModel, table=True):
    """1:1 link between a local board and a Google Flow project_id.

    Kept as a separate table so we don't have to migrate the Board schema.
    Paygate tier is loaded realtime from the extension via /api/auth/me,
    not persisted here — the binding is purely about project identity.
    """
    board_id: int = Field(primary_key=True, foreign_key="board.id")
    flow_project_id: str
    created_at: datetime = Field(default_factory=_utcnow)


class ProviderJob(SQLModel, table=True):
    """Handoff queue between the agent worker and external providers/agents.

    The "Muse" provider (Pax — the assistant itself) is a *delegated*
    backend: instead of calling a model API, the agent publishes a job
    here and an external worker claims it via ``routes/provider_jobs.py``,
    renders the media (or answers the LLM prompt) with its own tools, and
    posts the result back.

    Lifecycle: QUEUED → CLAIMED → RUNNING → SUCCEEDED | FAILED | CANCELLED.
    A claim grants a lease (``lease_expires_at``); the worker heartbeats to
    extend it. A crashed worker's lease expires and the job becomes
    reclaimable, so jobs are never stranded.
    """
    id: str = Field(primary_key=True)  # uuid4 hex
    provider: str = Field(index=True)  # "muse"
    # llm | image | edit_image | video (i2v) | video_refs (r2v)
    kind: str = Field(index=True)
    status: str = Field(default="QUEUED", index=True)
    prompt: str = ""
    orientation: Optional[str] = None  # VERTICAL | HORIZONTAL
    source_url: Optional[str] = None  # edit_image input (file:// or https://)
    start_url: Optional[str] = None  # i2v start frame
    end_url: Optional[str] = None
    reference_urls: list = Field(default_factory=list, sa_column=Column(JSON))
    extra: dict = Field(default_factory=dict, sa_column=Column(JSON))
    claimed_by: Optional[str] = None
    claimed_at: Optional[datetime] = None
    lease_expires_at: Optional[datetime] = None
    progress: int = 0
    progress_message: Optional[str] = None
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class AutoPlan(SQLModel, table=True):
    """A fixed posting schedule for one Facebook Page ("🤖 Tự động đăng" on the Posts page, services/autopilot):
    on ``days`` at ``times`` (Vietnam time) a post is written ``lead_minutes`` ahead with ``brief`` (the Posts form),
    pictured through Flow, and put on the calendar as an auto slot — nobody has to do anything. A slot that has no
    post ready by its time is skipped, never filled with something half-made. ``create_all`` adds the table."""
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(index=True)
    name: str = ""
    enabled: bool = Field(default=True, index=True)
    days: list = Field(default_factory=list, sa_column=Column(JSON))  # weekdays 0 = Monday … 6 = Sunday
    times: list = Field(default_factory=list, sa_column=Column(JSON))  # "HH:MM", Vietnam time
    lead_minutes: int = 180  # how long before the slot the post is written
    brief: dict = Field(default_factory=dict, sa_column=Column(JSON))  # kind, topic, tone, length, cta, images…
    series: str = ""  # every slot = the next episode of this story
    product_mode: str = "none"  # none | fixed | rotate (product_ids taken in turn)
    product_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    ai: str = "claude"  # claude (the Claude CLI) | gemini (the Gemini API key pool); the other one if it fails
    fb_story: bool = False  # "📲 Thêm vào tin" on every post
    enabled_at: datetime = Field(default_factory=_utcnow)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class AutoRun(SQLModel, table=True):
    """One slot of an :class:`AutoPlan`: the post written for it and the calendar slot it went on. Unique per
    (plan, slot time) — inserting the row is the claim, so two machines on the same database never both write
    for one slot; ``lease_until`` keeps a second machine off a run another one is still working on."""
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(index=True)
    slot_at: datetime = Field(index=True)  # UTC
    # writing → pictures → ready (then the Schedule slot says posted / failed) | waiting (retry) | failed | skipped | missed
    status: str = Field(default="writing", index=True)
    post_id: Optional[int] = None
    schedule_id: Optional[int] = None
    product_id: Optional[int] = None
    ai_used: str = ""
    image_requests: list = Field(default_factory=list, sa_column=Column(JSON))  # Flow request ids, kept for a restart
    attempts: int = 0
    error: str = ""
    note: str = ""
    lease_until: Optional[datetime] = None
    next_try_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    __table_args__ = (UniqueConstraint("plan_id", "slot_at", name="uq_autorun_plan_slot"),)


class GrabChannel(SQLModel, table=True):
    """A source channel on "📡 Cào video kênh" (services/channel_grab): a YouTube channel / playlist or a TikTok
    account whose videos are listed (title, views, date, length) so the seller picks what to download, cut and dub.
    ``key`` is the canonical form (``youtube:@handle``, ``tiktok:@user``…) — one row per channel however its link
    was pasted. ``tags`` are the seller's own labels. ``create_all`` adds the table."""
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True)
    platform: str = ""  # youtube | tiktok
    url: str = ""
    handle: str = ""
    name: str = ""
    avatar: str = ""  # the picture's source URL (cached on this machine when the channel is scanned)
    followers: Optional[int] = None
    description: str = ""
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    note: str = ""
    scanned_at: Optional[datetime] = None
    scan_error: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class GrabVideo(SQLModel, table=True):
    """One video listed from a :class:`GrabChannel`. ``media_id`` = downloaded (an Asset of this account);
    ``fresh`` = first seen in the newest scan; ``used`` = sent on to a tool ({"cut": iso time, "dub": …})."""
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(index=True)
    key: str = Field(index=True)  # <platform>:<video id>
    url: str = ""
    title: str = ""
    kind: str = "video"  # video | short (YouTube Shorts)
    duration_s: Optional[float] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    published_at: Optional[datetime] = None
    thumb: str = ""
    position: int = 0  # its place in the channel's own (newest first) list
    fresh: bool = False
    media_id: Optional[str] = None
    downloaded_at: Optional[datetime] = None
    download_error: str = ""
    used: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    __table_args__ = (UniqueConstraint("channel_id", "key", name="uq_grabvideo_channel_key"),)


class GrabMark(SQLModel, table=True):
    """What the seller noted on a listed video ("Đã xử lý", "Đã đăng", own labels) and which tools it went to — kept by
    the video's ``key`` (``<platform>:<video id>``), not by the listing row: rescans, removing and re-adding the channel
    or the same video showing in two lists all find it again. ``create_all`` adds the table."""
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    used: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=_utcnow)
