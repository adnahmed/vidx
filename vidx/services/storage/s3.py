from __future__ import annotations

import io
import os
import uuid as std_uuid
from typing import Union

import boto3
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

    async def generate_download_url(self, location: str) -> str:
        # If location looks like an s3 key, presign; if it's already a URL, return as-is
        if location.startswith("http://") or location.startswith("https://"):
            return location
        return self.generate_download_url_sync(location)

    def generate_download_url_sync(self, key: str) -> str:
        return self._s3.generate_presigned_url(
            "getObject",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=settings.s3_presign_expiry_seconds,
        )
