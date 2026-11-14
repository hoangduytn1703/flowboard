"""Media files shared through an S3 bucket (moto's in-memory S3), under the
active account's prefix."""
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from flowboard import config
from flowboard.db import get_session
from flowboard.db.models import Asset
from flowboard.services import file_store


@pytest.fixture
def bucket(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("FLOWBOARD_S3_ENDPOINT", "https://s3.us-east-1.amazonaws.com")
        monkeypatch.setenv("FLOWBOARD_S3_BUCKET", "flowboard-test")
        monkeypatch.setenv("FLOWBOARD_S3_KEY_ID", "test")
        monkeypatch.setenv("FLOWBOARD_S3_SECRET", "test")
        monkeypatch.setenv("FLOWBOARD_S3_REGION", "us-east-1")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
        file_store.reset()
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="flowboard-test")
        file_store.install_hooks()
        yield boto3.client("s3", region_name="us-east-1")
        file_store.wait_idle()
        file_store.reset()


def _media(name: str, data: bytes = b"video-bytes") -> Path:
    p = Path(config.STORAGE_DIR) / "media" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_not_configured_is_a_no_op(monkeypatch, tmp_path):
    for k in ("FLOWBOARD_S3_ENDPOINT", "FLOWBOARD_S3_BUCKET", "FLOWBOARD_S3_KEY_ID", "FLOWBOARD_S3_SECRET"):
        monkeypatch.delenv(k, raising=False)
    file_store.reset()
    assert not file_store.enabled()
    assert file_store.ensure_local(str(tmp_path / "missing.mp4")) is None
    assert file_store.reconcile() == {"queued": 0, "downloaded": 0, "repaired": 0, "reuploaded": 0}


def test_region_from_endpoint():
    assert file_store.region_from_endpoint("https://s3.us-west-004.backblazeb2.com") == "us-west-004"
    assert file_store.region_from_endpoint("https://abc.r2.cloudflarestorage.com") == "auto"


def test_new_asset_is_uploaded_under_the_account_prefix(bucket):
    p = _media("export_abc.mp4")
    with get_session() as s:
        s.add(Asset(kind="video", uuid_media_id="e" * 32, local_path=str(p), mime="video/mp4"))
        s.commit()
    file_store.wait_idle()
    key = file_store.prefix() + "media/export_abc.mp4"
    assert key.startswith("local/")  # no login in the suite
    assert bucket.get_object(Bucket="flowboard-test", Key=key)["Body"].read() == b"video-bytes"


def test_missing_file_is_fetched_from_the_bucket(bucket):
    bucket.put_object(Bucket="flowboard-test", Key=file_store.prefix() + "media/from_other_machine.mp4", Body=b"other")
    target = Path(config.STORAGE_DIR) / "media" / "from_other_machine.mp4"
    if target.exists():
        target.unlink()
    assert file_store.ensure_local(str(target)) == target and target.read_bytes() == b"other"
    before = file_store.status()["download_errors"]
    assert file_store.ensure_local(str(Path(config.STORAGE_DIR) / "media" / "nowhere.mp4")) is None
    assert file_store.status()["download_errors"] == before


def test_daily_download_cap_pauses_downloads_until_reset(bucket, monkeypatch):
    """B2's "cap exceeded" refusal (14/11): one try, then no more calls until 00:00 UTC, and a sentence instead of a signed URL."""
    calls = []

    class Capped:
        def download_file(self, Bucket, Key, Filename):  # noqa: N803
            calls.append(Key)
            raise file_store._BucketRefused("HTTP 403: Cannot download file, download bandwidth or transaction (Class B) cap exceeded.")

    monkeypatch.setattr(file_store, "_stats", dict(file_store._stats))  # the counters are process-wide; leave them as found
    monkeypatch.setattr(file_store, "client", lambda: Capped())
    target = Path(config.STORAGE_DIR) / "media" / "capped_a.mp4"
    assert file_store.ensure_local(str(target)) is None
    assert file_store.ensure_local(str(Path(config.STORAGE_DIR) / "media" / "capped_b.mp4")) is None
    assert len(calls) == 1
    st = file_store.status()
    assert st["downloads_paused"] and st["last_error"] == file_store.DOWNLOAD_CAP_MESSAGE
    file_store.reset()
    assert not file_store.status()["downloads_paused"]


def test_bucket_errors_hide_the_signed_query_and_read_the_message():
    url = "https://s3.us-east-005.backblazeb2.com/b/akira/media/x.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc"
    assert "X-Amz" not in file_store._short_error(RuntimeError(f"Client error '403 ' for url '{url}'"))
    body = "<Error><Code>AccessDenied</Code><Message>Cannot upload files, storage cap exceeded.</Message></Error>"
    assert file_store._bucket_message(body) == "Cannot upload files, storage cap exceeded."
    assert file_store._cap_exceeded(file_store._BucketRefused("HTTP 403: " + file_store._bucket_message(body)))


def test_reconcile_pushes_local_and_pulls_remote(bucket):
    local = _media("local_only.png", b"png")
    remote_target = Path(config.STORAGE_DIR) / "media" / "remote_only.png"
    if remote_target.exists():
        remote_target.unlink()
    bucket.put_object(Bucket="flowboard-test", Key=file_store.prefix() + "media/remote_only.png", Body=b"remote")
    with get_session() as s:
        s.add(Asset(kind="image", uuid_media_id="l" * 32, local_path=str(local)))
        s.add(Asset(kind="image", uuid_media_id="r" * 32, local_path=str(remote_target)))
        s.commit()
    file_store.wait_idle()
    bucket.delete_object(Bucket="flowboard-test", Key=file_store.prefix() + "media/local_only.png")
    file_store.reset()
    out = file_store.reconcile()
    file_store.wait_idle()
    assert out["downloaded"] == 1 and remote_target.read_bytes() == b"remote"
    assert bucket.get_object(Bucket="flowboard-test", Key=file_store.prefix() + "media/local_only.png")["Body"].read() == b"png"
