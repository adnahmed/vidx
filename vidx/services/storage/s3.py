from __future__ import annotations

import uuid as std_uuid
from pathlib import Path
from typing import Union

import boto3
import httpx
from fastapi import UploadFile

from vidx.settings import settings

from .base import StorageProvider


class AWSS3Strategy(StorageProvider):
    def __init__(self) -> None:
        # Support LocalStack via custom endpoint
        self._s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=settings.aws_session_token,
            endpoint_url=settings.aws_endpoint_url,
        )
        if not settings.s3_bucket:
            raise RuntimeError("AWS_S3_BUCKET not configured")
        self._bucket = settings.s3_bucket

    async def save_upload(self, upload: Union[UploadFile, str]) -> str:
        if isinstance(upload, str):
            # Assume string is already a URL (e.g., pre-signed); return as-is
            return upload

        key = f"uploads/{std_uuid.uuid4().hex}/{upload.filename or 'file'}"
        await upload.seek(0)
        data = await upload.read()
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data)
        # Return a pre-signed URL for immediate downstream consumption by ffmpeg
        return self.generate_download_url_sync(key)

    async def save_bytes(self, data: bytes, filename: str) -> str:
        key = f"generated/{std_uuid.uuid4().hex}/{self._safe_filename(filename)}"
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data)
        # Return the durable key; presign on demand when serving.
        return key

    async def generate_download_url(self, location: str) -> str:
        # If location looks like an s3 key, presign; if it's already a URL, return as-is
        if location.startswith(("http://", "https://")):
            return location
        if Path(location).is_absolute() and Path(location).exists():
            raise RuntimeError("Local path cannot be served by S3 storage")
        return self.generate_download_url_sync(location)

    async def materialize(self, location: str) -> str:
        if location.startswith(("http://", "https://")):
            target = self._temp_path(location)
            async with httpx.AsyncClient(
                timeout=float(settings.provider_download_timeout_seconds),
                follow_redirects=True,
            ) as client, client.stream("GET", location) as response:
                response.raise_for_status()
                with target.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
            return str(target)
        # Treat as an object key: download from S3 into a temp file.
        target = self._temp_path(location)
        self._s3.download_file(self._bucket, location, str(target))
        return str(target)

    def generate_download_url_sync(self, key: str) -> str:
        return self._s3.generate_presigned_url(
            "getObject",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=settings.s3_presign_expiry_seconds,
        )
