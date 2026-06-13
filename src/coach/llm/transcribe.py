"""P10-T5 / Step 10b — voice→text transcription seam (Amazon Transcribe).

Mirrors `llm/client.py` and `llm/embeddings.py`: an interface, a lazy real provider (Amazon
Transcribe — region from config; boto3 imported on first use), and a deterministic fake for tests
(no live AWS calls). Production swaps the provider behind `Transcriber`.

This is the INPUT method only for the CLOSE capture: it turns a post-ride voice recording into
text. The text then flows through the SAME Step 10a write path (writer-scope RBAC + PRP on
readback) — voice does not change any write/RBAC/PRP rule. The assistant only records the DM's
own words; it takes no autonomous action.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from coach.config.settings import get_settings


@runtime_checkable
class Transcriber(Protocol):
    """Turn a voice recording into text. Same shape for MVP (fake) and production (Amazon)."""

    def transcribe(self, audio: bytes) -> str: ...


class FakeTranscriber:
    """Deterministic, offline transcriber for tests — returns a FIXED transcript regardless of the
    audio bytes (same shape as `FakeLLM` / `FakeEmbeddings`). No live AWS call."""

    def __init__(self, transcript: str) -> None:
        self.transcript = transcript

    def transcribe(self, audio: bytes) -> str:
        return self.transcript


class AmazonTranscribe:
    """Real Amazon Transcribe (voice→text). Region comes from config — never hard-coded
    (Constitution VIII); boto3 is imported lazily so importing this module needs no AWS creds. Not
    exercised by tests; the real path lives behind `Transcriber` and uses the configured S3 bucket
    for the media + job output."""

    def __init__(self, region: str | None = None, s3_bucket: str | None = None) -> None:
        s = get_settings()
        self.region = region or s.aws_region
        self.s3_bucket = s3_bucket or s.transcribe_s3_bucket
        self._transcribe = None
        self._s3 = None

    def _clients(self):  # pragma: no cover - real AWS path, not unit-tested
        if self._transcribe is None:
            import boto3  # lazy import so the module loads without boto3/credentials

            self._transcribe = boto3.client("transcribe", region_name=self.region)
            self._s3 = boto3.client("s3", region_name=self.region)
        return self._transcribe, self._s3

    def transcribe(self, audio: bytes) -> str:  # pragma: no cover - real AWS path
        """Production: upload the recording to S3, start a transcription job, poll to completion,
        and return the transcript text. (Tests use `FakeTranscriber`; this path is never run in
        CI.)"""
        import json
        import time
        import urllib.request
        import uuid

        if not self.s3_bucket:
            raise ValueError(
                "TRANSCRIBE_S3_BUCKET is not configured (required for Amazon Transcribe)."
            )
        transcribe, s3 = self._clients()
        job = f"close-{uuid.uuid4().hex}"
        key = f"close-audio/{job}"
        s3.put_object(Bucket=self.s3_bucket, Key=key, Body=audio)
        transcribe.start_transcription_job(
            TranscriptionJobName=job,
            Media={"MediaFileUri": f"s3://{self.s3_bucket}/{key}"},
            IdentifyLanguage=True,
            OutputBucketName=self.s3_bucket,
        )
        while True:
            status = transcribe.get_transcription_job(TranscriptionJobName=job)
            state = status["TranscriptionJob"]["TranscriptionJobStatus"]
            if state in ("COMPLETED", "FAILED"):
                break
            time.sleep(2)
        if state == "FAILED":
            raise RuntimeError(f"Amazon Transcribe job {job} failed")
        uri = status["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
        with urllib.request.urlopen(uri) as resp:  # noqa: S310 - AWS-presigned transcript URL
            payload = json.loads(resp.read())
        return payload["results"]["transcripts"][0]["transcript"]
