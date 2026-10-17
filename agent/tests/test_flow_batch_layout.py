"""The ogiZ0b wire layout the current Flow UI sends, synced from flowkit.

flowboard's older layout put a client uuid in the item's second-to-last slot
and never named an edit's asset in the context; on 2026-10-11 live Flow
answered an image request built that way with ``[5]`` (NOT_FOUND). This is the
layout flowkit sends, live-captured from the Flow UI.
"""
from flowboard.services import flow_batch as fb
from tests.batch_harness import decode_freq, image_items

PID = "e22fe3ef-902d-4248-8a65-f95d8b84f1b7"
REF_A = "7483a61d-2d91-4e72-8a38-a5789d2ca291"
REF_B = "9bc14c3b-7ab3-43b8-b2ea-39abcb921bd6"
BASE = "c7fab458-56b8-451b-85cf-73d167995c1e"

ASSET_SLOT = 4      # in _context
PROJECT_SLOT = 5    # in _context


def _payload(**kw):
    return decode_freq(fb.image_request("a prompt", PID, **kw))


def test_item_tail_has_one_client_uuid_after_an_empty_slot():
    for item in image_items(_payload(count=2, ref_media_ids=[REF_A, REF_B])):
        assert item[-2] is None, "a uuid here comes back [5] NOT_FOUND"
        assert isinstance(item[-1], str) and len(item[-1]) == 36


def test_generate_leaves_the_context_asset_slot_empty():
    payload = _payload(ref_media_ids=[REF_A])
    for ctx in [payload[3]] + [item[7] for item in image_items(payload)]:
        assert ctx[ASSET_SLOT] is None
        assert ctx[PROJECT_SLOT] == PID


def test_edit_names_its_base_image_as_the_context_asset():
    payload = _payload(base_media_id=BASE, ref_media_ids=[REF_A])
    for ctx in [payload[3]] + [item[7] for item in image_items(payload)]:
        assert ctx[ASSET_SLOT] == BASE


def test_listing_lookup_reads_the_current_entry_shape():
    """``[assetId, folderId, null, [title, [sec, nanos], isVideo, null, mediaId, opId, done], pid]``"""
    op, media = "op-123", "11111111-2222-4333-8444-555555555555"
    listing = [["asset-1", "folder-1", None, ["t", [1, 2], True, None, media, op, True], PID]]
    assert fb.find_media_id(listing, op) == media
    assert fb.find_media_id(listing, op.upper()) == media
