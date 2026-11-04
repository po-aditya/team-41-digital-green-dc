"""SpeechToText implementations."""
from __future__ import annotations

import json
import time
import uuid
from typing import Optional, Sequence


class FakeSTT:
    """Returns scripted text, one entry per call; empty string once the script runs out."""

    def __init__(self, script: Optional[Sequence[str]] = None) -> None:
        self._script = list(script or [])

    def transcribe(self, audio_bytes: bytes, language: str) -> str:
        return self._script.pop(0) if self._script else ""


class TranscribeSTT:
    """Amazon Transcribe batch job (hi-IN, en-IN). Needs an S3 bucket for audio and output."""

    def __init__(self, region: str, bucket: str, prefix: str = "jaak-voice/",
                 poll_seconds: float = 1.0, timeout_seconds: float = 90.0) -> None:
        import boto3
        self._s3 = boto3.client("s3", region_name=region)
        self._tr = boto3.client("transcribe", region_name=region)
        self._bucket, self._prefix = bucket, prefix
        self._poll, self._timeout = poll_seconds, timeout_seconds

    def transcribe(self, audio_bytes: bytes, language: str) -> str:
        if language not in ("hi-IN", "en-IN"):
            raise ValueError("unsupported language")
        job = f"jaak-{uuid.uuid4().hex}"
        in_key, out_key = f"{self._prefix}in/{job}.wav", f"{self._prefix}out/{job}.json"
        self._s3.put_object(Bucket=self._bucket, Key=in_key, Body=audio_bytes)
        try:
            self._tr.start_transcription_job(
                TranscriptionJobName=job, LanguageCode=language, MediaFormat="wav",
                Media={"MediaFileUri": f"s3://{self._bucket}/{in_key}"},
                OutputBucketName=self._bucket, OutputKey=out_key)
            deadline = time.monotonic() + self._timeout
            while True:
                status = self._tr.get_transcription_job(TranscriptionJobName=job)["TranscriptionJob"]["TranscriptionJobStatus"]
                if status == "COMPLETED":
                    break
                if status == "FAILED" or time.monotonic() > deadline:
                    return ""
                time.sleep(self._poll)
            body = self._s3.get_object(Bucket=self._bucket, Key=out_key)["Body"].read()
            return json.loads(body)["results"]["transcripts"][0]["transcript"].strip()
        finally:
            for key in (in_key, out_key):
                try:
                    self._s3.delete_object(Bucket=self._bucket, Key=key)
                except Exception:  # noqa: BLE001
                    pass
            try:
                self._tr.delete_transcription_job(TranscriptionJobName=job)
            except Exception:  # noqa: BLE001
                pass
