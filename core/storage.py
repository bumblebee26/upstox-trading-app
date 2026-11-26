"""Where state lives: the upx-state S3 bucket when UPX_STATE_BUCKET is set (GitHub session, Lambdas),
otherwise local files under UPX_DATA_DIR (tests, a run on the PC). Same small interface for both."""
import json
import os
from pathlib import Path


class Local:
    def __init__(self, root):
        self.root = Path(root)

    def get(self, key):
        p = self.root / key
        return p.read_bytes() if p.exists() else None

    def put(self, key, body):
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)

    def list(self, prefix):
        base = self.root / prefix
        folder = base if prefix.endswith("/") else base.parent
        if not folder.exists():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in folder.rglob("*")
                      if p.is_file() and p.relative_to(self.root).as_posix().startswith(prefix))

    def claim(self, key):
        """Create key only if it doesn't exist yet; True for the one caller that made it."""
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.close(os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            return False


class S3:
    def __init__(self, bucket):
        import boto3  # only in AWS and the GitHub session

        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-southeast-2"))
        self.errors = self.s3.exceptions

    def get(self, key):
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.errors.NoSuchKey:
            return None

    def put(self, key, body):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body)

    def list(self, prefix):
        keys = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return sorted(keys)

    def claim(self, key):
        try:  # S3 conditional write: fails if the object already exists
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=b"", IfNoneMatch="*")
            return True
        except self.s3.exceptions.ClientError as err:
            if err.response.get("Error", {}).get("Code") in ("PreconditionFailed", "ConditionalRequestConflict"):
                return False
            raise


_backend = None


def backend():
    global _backend
    if _backend is None:
        bucket = os.environ.get("UPX_STATE_BUCKET")
        _backend = S3(bucket) if bucket else Local(os.environ.get("UPX_DATA_DIR", "data"))
    return _backend


def get_json(key, default=None, store=None):
    body = (store or backend()).get(key)
    return json.loads(body) if body is not None else default


def put_json(key, value, store=None):
    (store or backend()).put(key, json.dumps(value, ensure_ascii=False).encode())
