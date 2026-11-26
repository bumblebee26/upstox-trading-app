"""Secrets from AWS SSM Parameter Store, read once per process.

Only /upx/ parameters are allowed, so this repo can never depend on a parameter the old repos own
(removing the old stacks deletes those).
"""
import os

_cache = {}


def get(name, client=None):
    if not name.startswith("/upx/"):
        raise ValueError(f"{name}: only /upx/ parameters belong to this repo")
    if name not in _cache:
        if client is None:
            import boto3  # in the Lambda runtime and CI; not needed for tests

            client = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "ap-southeast-2"))
        _cache[name] = client.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    return _cache[name]
