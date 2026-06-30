from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import base64
import json
import os
import sys
import mimetypes
import http.client

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


FILES = collect_files()


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
            try:
                raw_bytes = response.read()
            except http.client.IncompleteRead as incomplete:
                raw_bytes = incomplete.partial or b""
            raw = raw_bytes.decode("utf-8", errors="replace")
            try:
                return response.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return response.status, {"message": raw}
    except HTTPError as error:
        try:
            raw_bytes = error.read()
        except http.client.IncompleteRead as incomplete:
            raw_bytes = incomplete.partial or b""
        raw = raw_bytes.decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"message": raw}
        return error.code, body


def remote_sha(path, token):
    encoded_path = quote(path, safe='/')
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{encoded_path}?ref={BRANCH}"
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
    payload = {
        "message": f"Upload {path}",
        "content": content,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    encoded_path = quote(path, safe='/')
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{encoded_path}"
    status, body = api_request("PUT", url, token, payload)
    if status not in (200, 201):
        raise RuntimeError(f"Upload failed for {path}: {body.get('message', body)}")
    action = "Updated" if status == 200 else "Created"
    print(f"{action}: {path}")


def get_token():
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GIT_TOKEN"):
        value = os.getenv(key)
        if value:
            return value
    if len(sys.argv) > 1:
        return sys.argv[1]
    return input("Paste GitHub token with repository Contents read/write access: ").strip()


def main():
    print(f"Uploading PSA Search System to https://github.com/{OWNER}/{REPO}")
    token = get_token()
    if not token:
        raise SystemExit("No token provided.")
    if token in {"password", "123456"}:
        raise SystemExit("Invalid input. Use a real GitHub personal access token.")
    for path in FILES:
        upload_file(path, token)
    print("Done. Open the repository to verify the files.")


if __name__ == "__main__":
    main()
