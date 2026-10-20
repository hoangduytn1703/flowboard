import { useEffect, useState } from "react";
import type { LLMProviderName } from "../../api/client";

/**
 * Inline setup guide opened from the "Setup help" button on each
 * provider row. Content varies by provider per the plan UI Spec:
 *   - Claude: install + auth + verify (CLI subscription)
 *   - Gemini: install + auth + verify (CLI subscription)
 *   - OpenAI: 2-tab layout — Codex CLI (preferred) / API key (fallback)
 *
 * Backdrop click + ESC + Close button all dismiss. Focus trap is
 * provided by the Settings panel backdrop already (we render inside it).
 */

interface ProviderSetupModalProps {
  provider: LLMProviderName;
  open: boolean;
  onClose(): void;
}

interface CommandLineProps {
  cmd: string;
}

function CommandLine({ cmd }: CommandLineProps) {
  const [copied, setCopied] = useState(false);
  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can fail on insecure contexts — silently no-op,
      // user can still select+copy by hand.
    }
  }
  return (
    <div className="setup-modal__cmd">
      <code className="setup-modal__cmd-text">{cmd}</code>
      <button
        type="button"
        className="setup-modal__copy"
        onClick={handleCopy}
        aria-label="Sao chép lệnh"
      >
        {copied ? "✓ Đã chép" : "Sao chép"}
      </button>
    </div>
  );
}

export function ProviderSetupModal({ provider, open, onClose }: ProviderSetupModalProps) {
  // OpenAI is the only modal with tabs. Default to "cli" (the recommended
  // path); user can flip to "api" for the fallback.
  const [openaiTab, setOpenaiTab] = useState<"cli" | "api">("cli");

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="setup-modal-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="setup-modal" role="dialog" aria-modal="true">
        <div className="setup-modal__header">
          <span className="setup-modal__title">{titleFor(provider)}</span>
          <button
            type="button"
            className="setup-modal__close"
            onClick={onClose}
            aria-label="Đóng hướng dẫn"
          >
            ×
          </button>
        </div>

        {provider === "claude" && <ClaudeContent />}
        {provider === "gemini" && <GeminiContent />}
        {provider === "openai" && (
          <OpenAiContent tab={openaiTab} onTabChange={setOpenaiTab} />
        )}
        {provider === "muse" && <MuseContent />}

        <div className="setup-modal__footer">
          <a
            className="setup-modal__docs-link"
            href={docsLinkFor(provider)}
            target="_blank"
            rel="noopener noreferrer"
          >
            Mở tài liệu {labelFor(provider)} ↗
          </a>
          <button
            type="button"
            className="setup-modal__close-btn"
            onClick={onClose}
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
}

function ClaudeContent() {
  return (
    <div className="setup-modal__body">
      <p>
        Flowboard dùng gói Claude bạn đang có thông qua CLI chính thức —
        không cần API key.
      </p>
      <ol className="setup-modal__steps">
        <li>
          <span className="setup-modal__step-label">Cài đặt</span>
          <CommandLine cmd="npm install -g @anthropic-ai/claude-code" />
        </li>
        <li>
          <span className="setup-modal__step-label">Đăng nhập</span>
          <CommandLine cmd="claude" />
          <span className="setup-modal__step-hint">
            Mở trình duyệt để đăng nhập OAuth — đăng nhập bằng tài khoản Claude của bạn.
          </span>
        </li>
        <li>
          <span className="setup-modal__step-label">Kiểm tra phiên bản</span>
          <CommandLine cmd="claude --version" />
        </li>
      </ol>
      <p className="setup-modal__note">
        Cài đặt và đăng nhập xong, dòng Claude ở trên sẽ tự chuyển sang
        ✓ Đã kết nối (bảng này tự kiểm tra mỗi 30 giây).
      </p>
    </div>
  );
}

function GeminiContent() {
  return (
    <div className="setup-modal__body">
      <p>
        Flowboard dùng gói Gemini bạn đang có thông qua CLI chính thức —
        không cần API key.
      </p>
      <ol className="setup-modal__steps">
        <li>
          <span className="setup-modal__step-label">Cài đặt</span>
          <CommandLine cmd="npm install -g @google/gemini-cli" />
        </li>
        <li>
          <span className="setup-modal__step-label">Đăng nhập</span>
          <CommandLine cmd="gemini auth login" />
        </li>
        <li>
          <span className="setup-modal__step-label">Kiểm tra phiên bản</span>
          <CommandLine cmd="gemini --version" />
        </li>
      </ol>
      <p className="setup-modal__note">
        Đăng nhập xong, dòng Gemini sẽ chuyển sang ✓ Đã kết nối ở lần
        kiểm tra 30 giây kế tiếp.
      </p>
    </div>
  );
}

interface OpenAiContentProps {
  tab: "cli" | "api";
  onTabChange(t: "cli" | "api"): void;
}

function OpenAiContent({ tab, onTabChange }: OpenAiContentProps) {
  return (
    <div className="setup-modal__body">
      <div className="setup-modal__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "cli"}
          className={`setup-modal__tab${tab === "cli" ? " setup-modal__tab--active" : ""}`}
          onClick={() => onTabChange("cli")}
        >
          Codex CLI (khuyên dùng)
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "api"}
          className={`setup-modal__tab${tab === "api" ? " setup-modal__tab--active" : ""}`}
          onClick={() => onTabChange("api")}
        >
          API key
        </button>
      </div>

      {tab === "cli" ? (
        <>
          <p>Cần gói ChatGPT Plus hoặc Pro.</p>
          <ol className="setup-modal__steps">
            <li>
              <span className="setup-modal__step-label">Cài đặt</span>
              <CommandLine cmd="npm install -g @openai/codex" />
            </li>
            <li>
              <span className="setup-modal__step-label">Đăng nhập</span>
              <CommandLine cmd="codex login" />
            </li>
            <li>
              <span className="setup-modal__step-label">Kiểm tra phiên bản</span>
              <CommandLine cmd="codex --version" />
            </li>
          </ol>
          <p className="setup-modal__note">
            Nếu bản Codex của bạn chỉ xử lý văn bản, bạn có thể thêm API key
            OpenAI ở dòng OpenAI phía trên để dự phòng cho Vision.
          </p>
        </>
      ) : (
        <>
          <p>Dành cho người không có ChatGPT Plus hoặc Pro.</p>
          <ol className="setup-modal__steps">
            <li>
              <span className="setup-modal__step-label">Lấy key</span>
              <a
                className="setup-modal__step-link"
                href="https://platform.openai.com/api-keys"
                target="_blank"
                rel="noopener noreferrer"
              >
                platform.openai.com/api-keys ↗
              </a>
            </li>
            <li>
              <span className="setup-modal__step-label">Lưu key</span>
              <span className="setup-modal__step-hint">
                Dán vào dòng OpenAI phía trên rồi bấm Lưu.
              </span>
            </li>
          </ol>
          <p className="setup-modal__note">
            Key được lưu trong <code>~/.flowboard/secrets.json</code>{" "}
            (quyền 600, chỉ trên máy bạn) và không bao giờ gửi đi đâu ngoài
            api.openai.com.
          </p>
        </>
      )}
    </div>
  );
}

function MuseContent() {
  return (
    <div className="setup-modal__body">
      <p>
        Muse không cần CLI và không cần nhập key trong hộp thoại này. Chọn
        một cách kết nối: cổng <strong>muse2api</strong> (muse.ai dưới dạng
        API tương thích OpenAI), hoặc <strong>Pax worker</strong> lấy việc
        từ hàng đợi của Flowboard.
      </p>
      <ol className="setup-modal__steps">
        <li>
          <span className="setup-modal__step-label">
            Cách A — cổng muse2api
          </span>
          <CommandLine cmd="FLOWBOARD_MUSE2API_BASE=http://127.0.0.1:18610" />
          <CommandLine cmd="FLOWBOARD_MUSE2API_KEY=<MUSE2API_API_KEY>" />
          <span className="setup-modal__step-hint">
            Thêm cả hai vào <code>.env</code> ở thư mục gốc rồi khởi động lại
            agent. Các tính năng LLM, tạo ảnh và video sẽ gọi thẳng muse2api;
            dòng này chuyển sang ✓ Đã kết nối khi /readyz báo sẵn sàng.
          </span>
        </li>
        <li>
          <span className="setup-modal__step-label">
            Cách B — Pax worker
          </span>
          <CommandLine cmd="python agent/scripts/muse_worker.py --worker-id pax-1" />
          <span className="setup-modal__step-hint">
            Chỉ dùng khi chưa đặt FLOWBOARD_MUSE2API_BASE. Chạy trên cùng máy
            với agent; dòng này chuyển sang ✓ Đã kết nối sau lần kiểm tra
            đầu tiên (~30 giây).
          </span>
        </li>
        <li>
          <span className="setup-modal__step-label">Kiểm tra</span>
          <span className="setup-modal__step-hint">
            Bấm “Kiểm tra” trên một dòng tính năng — hệ thống gửi một lượt
            thật và báo độ trễ.
          </span>
        </li>
      </ol>
      <p className="setup-modal__note">
        Xem docs/muse-provider.md để biết mỗi cách kết nối hỗ trợ gì.
      </p>
    </div>
  );
}

function titleFor(p: LLMProviderName): string {
  switch (p) {
    case "claude":
      return "🤖 Thiết lập Claude CLI";
    case "gemini":
      return "🤖 Thiết lập Gemini CLI";
    case "openai":
      return "🤖 Thiết lập OpenAI";
    case "muse":
      return "🤖 Thiết lập Muse";
  }
}

function labelFor(p: LLMProviderName): string {
  switch (p) {
    case "claude":
      return "Anthropic";
    case "gemini":
      return "Google Gemini";
    case "openai":
      return "OpenAI";
    case "muse":
      return "Muse";
  }
}

function docsLinkFor(p: LLMProviderName): string {
  switch (p) {
    case "claude":
      return "https://docs.anthropic.com/en/docs/claude-code/quickstart";
    case "gemini":
      return "https://github.com/google/gemini-cli";
    case "openai":
      return "https://platform.openai.com/docs/quickstart";
    case "muse":
      return "https://muse.ai";
  }
}
