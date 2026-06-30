from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import base64
import json
import os
import sys

OWNER = "cromuarpsa-rgb"
REPO = "PSA-SEARCH"
BRANCH = "main"
ROOT = Path(__file__).resolve().parent
IGNORED_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}


def collect_files():
    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(ROOT)
        if any(part in IGNORED_DIRS for part in rel_path.parts[:-1]):
            continue
        files.append(rel_path.as_posix())
    return files


def api_request(method, url, token, payload=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "PSA-Search-Uploader",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"message": raw}
        return error.code, body


def get_token():
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GIT_TOKEN"):
        value = os.getenv(key)
        if value:
            return value
    return None


def remote_sha(path, token):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}?ref={BRANCH}"
    status, body = api_request("GET", url, token)
    if status == 200:
        return body.get("sha")
    if status == 404:
        return None
    raise RuntimeError(f"Could not check {path}: {body.get('message', body)}")


def upload_file(path, token):
    local_path = ROOT / path
    if not local_path.exists():
        print(f"Skipped missing file: {path}")
        return
    content = base64.b64encode(local_path.read_bytes()).decode("ascii")
    sha = remote_sha(path, token)
    payload = {"message": f"Deploy {path}", "content": content, "branch": BRANCH}
    if sha:
        payload["sha"] = sha
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    status, body = api_request("PUT", url, token, payload)
    if status not in (200, 201):
        raise RuntimeError(f"Upload failed for {path}: {body.get('message', body)}")
    action = "Updated" if status == 200 else "Created"
    print(f"{action}: {path}")


def main():
    token = get_token()
    if not token:
        print("No GitHub token found in environment variables. Set GITHUB_TOKEN and rerun.")
        sys.exit(1)
    print(f"Uploading PSA Search System to https://github.com/{OWNER}/{REPO}")
    for path in collect_files():
        upload_file(path, token)
    print("Deployment complete.")


if __name__ == "__main__":
    main()
