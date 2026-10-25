import { useState } from "react";
import { patchBoardData } from "../../api/client";
import { useBoardStore } from "../../store/board";
import { toast } from "../../store/toast";
import { ChannelPicker, useChannels } from "../channels/ChannelPicker";

/**
 * Step 1, under the product: which channel (page) this clip is for. Saved
 * in `quicktool.channel_id`; step 5's post follows that channel.
 */
export function ClipChannel({ boardId, channelId }: { boardId: number; channelId: number | null }) {
  const [channels] = useChannels();
  const [busy, setBusy] = useState(false);
  if (channels.length === 0) return null;
  async function change(id: number | null) {
    setBusy(true);
    try {
      await patchBoardData(boardId, { quicktool: { channel_id: id } });
      await useBoardStore.getState().refreshBoardList();
      const name = channels.find((c) => c.id === id)?.name;
      toast.success(id ? `Clip thuộc kênh "${name}".` : "Đã bỏ gắn kênh.");
    } catch (e) {
      toast.error(`Không lưu được kênh: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="qt-card qt-clip-channel">
      <div className="qt-card__eyebrow">Kênh đăng</div>
      <ChannelPicker value={channelId} disabled={busy} onChange={(id) => void change(id)} label="Clip này làm cho kênh" />
    </section>
  );
}
