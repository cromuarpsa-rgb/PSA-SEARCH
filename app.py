from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import hashlib
import hmac
import html
import json
import mimetypes
import secrets
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGO_DIR = BASE_DIR / "logo"
LOG_DIR = BASE_DIR / "logs"
USER_FILE = BASE_DIR / "users.json"
APP_LOG = LOG_DIR / "activity.log"
HOST = "127.0.0.1"
PORT = 8000
SESSION_COOKIE = "psa_session"
SESSION_SECONDS = 8 * 60 * 60
MAX_RESULTS = 1000
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

sessions = {}
sessions_lock = threading.Lock()
cache_lock = threading.Lock()
workbook_cache = {"path": None, "mtime": None, "data": None}


def hash_password(salt, password):
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def ensure_files():
    LOG_DIR.mkdir(exist_ok=True)
    if not USER_FILE.exists():
        USER_FILE.write_text(json.dumps({"admin": {"salt": "psa-search-local", "password_hash": hash_password("psa-search-local", "admin123")}}, indent=2), encoding="utf-8")
    APP_LOG.touch(exist_ok=True)


def write_log(event, username="-", details="-"):
    ensure_files()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    clean = str(details).replace("\r", " ").replace("\n", " ")
    with APP_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp}\t{event}\t{username}\t{clean}\n")


def load_users():
    ensure_files()
    return json.loads(USER_FILE.read_text(encoding="utf-8"))


def check_login(username, password):
    user = load_users().get(username)
    if not user:
        return False
    actual = hash_password(user.get("salt", ""), password)
    return hmac.compare_digest(user.get("password_hash", ""), actual)


def create_session(username):
    token = secrets.token_urlsafe(32)
    with sessions_lock:
        sessions[token] = {"username": username, "expires": time.time() + SESSION_SECONDS}
    return token


def get_session(token):
    if not token:
        return None
    with sessions_lock:
        session = sessions.get(token)
        if not session:
            return None
        if session["expires"] < time.time():
            sessions.pop(token, None)
            return None
        session["expires"] = time.time() + SESSION_SECONDS
        return session


def clear_session(token):
    with sessions_lock:
        sessions.pop(token, None)


def latest_workbook():
    files = sorted(DATA_DIR.glob("*.xlsx"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError("No .xlsx file found inside the data folder.")
    return files[0]


def logo_file():
    for pattern in ("*.webp", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg"):
        files = sorted(LOGO_DIR.glob(pattern))
        if files:
            return files[0]
    return None


def column_index(ref):
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    number = 0
    for char in letters:
        number = number * 26 + ord(char) - ord("A") + 1
    return max(0, number - 1)


def text_of(element):
    if element is None:
        return ""
    return "".join(element.itertext())


def read_shared_strings(book):
    try:
        root_xml = ET.fromstring(book.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(item.itertext()) for item in root_xml.findall("m:si", NS)]


def read_sheet_targets(book):
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    sheets = []
    rid_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        target = rel_map.get(sheet.attrib.get(rid_key), "")
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        sheets.append((sheet.attrib["name"], target))
    return sheets


def read_cell(cell, strings):
    kind = cell.attrib.get("t")
    value = cell.find("m:v", NS)
    if kind == "s":
        raw = text_of(value)
        if raw.isdigit() and int(raw) < len(strings):
            return strings[int(raw)]
        return raw
    if kind == "inlineStr":
        return text_of(cell.find("m:is", NS))
    if kind == "b":
        return "TRUE" if text_of(value) == "1" else "FALSE"
    return text_of(value)


def parse_sheet(book, target, strings):
    root_xml = ET.fromstring(book.read(target))
    raw_rows = []
    for row in root_xml.findall("m:sheetData/m:row", NS):
        values = []
        for cell in row.findall("m:c", NS):
            index = column_index(cell.attrib.get("r", "")) if cell.attrib.get("r") else len(values)
            while len(values) <= index:
                values.append("")
            values[index] = read_cell(cell, strings).strip()
        if any(values):
            raw_rows.append(values)
    if not raw_rows:
        return {"columns": [], "rows": []}
    width = max(len(row) for row in raw_rows)
    header = raw_rows[0]
    columns = []
    seen = {}
    for index in range(width):
        name = header[index].strip() if index < len(header) else ""
        name = name or f"Column {index + 1}"
        seen[name] = seen.get(name, 0) + 1
        columns.append(name if seen[name] == 1 else f"{name} {seen[name]}")
    rows = []
    for raw in raw_rows[1:]:
        item = {column: raw[index] if index < len(raw) else "" for index, column in enumerate(columns)}
        if any(item.values()):
            rows.append(item)
    return {"columns": columns, "rows": rows}


def load_workbook():
    path = latest_workbook()
    mtime = path.stat().st_mtime
    with cache_lock:
        if workbook_cache["data"] and workbook_cache["path"] == str(path) and workbook_cache["mtime"] == mtime:
            return workbook_cache["data"]
        with zipfile.ZipFile(path) as book:
            strings = read_shared_strings(book)
            sheets = []
            for name, target in read_sheet_targets(book):
                parsed = parse_sheet(book, target, strings)
                sheets.append({"name": name, "columns": parsed["columns"], "rows": parsed["rows"], "count": len(parsed["rows"])})
        data = {"file": path.name, "sheets": sheets, "loaded_at": time.time()}
        workbook_cache.update({"path": str(path), "mtime": mtime, "data": data})
        return data


def row_matches(row, terms):
    haystack = " ".join(str(value).lower() for value in row.values())
    return all(term in haystack for term in terms)


def search_data(sheet_name, query):
    workbook = load_workbook()
    terms = [term.lower() for term in query.split() if term.strip()]
    all_sheets = sheet_name in ("", "all")
    selected = workbook["sheets"] if all_sheets else [s for s in workbook["sheets"] if s["name"] == sheet_name]
    columns = []
    rows = []
    total = 0
    sheet_counts = {}
    for sheet in selected:
        display_columns = ["Sheet"] + sheet["columns"] if all_sheets else sheet["columns"]
        for column in display_columns:
            if column not in columns:
                columns.append(column)
        matched = []
        for row in sheet["rows"]:
            if not terms or row_matches(row, terms):
                matched.append({"Sheet": sheet["name"], **row} if all_sheets else row)
        sheet_counts[sheet["name"]] = len(matched)
        total += len(matched)
        rows.extend(matched[: max(0, MAX_RESULTS - len(rows))])
        if len(rows) >= MAX_RESULTS:
            break
    return {"file": workbook["file"], "sheets": [{"name": s["name"], "count": s["count"]} for s in workbook["sheets"]], "columns": columns, "rows": rows, "result_count": len(rows), "total_matches": total, "sheet_counts": sheet_counts, "limited": total > len(rows), "max_results": MAX_RESULTS}


CSS = r'''
:root{--blue:#164e9f;--red:#c3262e;--gold:#f3b43f;--ink:#132033;--muted:#637083;--line:#d8e0ea;--bg:#eef3f8;--surface:#fff}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif}.login-body{display:grid;place-items:center;padding:28px;background:linear-gradient(120deg,rgba(22,78,159,.94),rgba(195,38,46,.82)),var(--bg)}.login-shell{width:min(960px,100%);min-height:560px;display:grid;grid-template-columns:1.1fr .9fr;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 24px 70px rgba(15,23,42,.25)}.login-brand{display:flex;flex-direction:column;justify-content:center;padding:56px;color:white;background:linear-gradient(145deg,rgba(22,78,159,.94),rgba(16,42,86,.96))}.login-logo{width:108px;height:108px;object-fit:contain;background:white;border-radius:8px;padding:10px;margin-bottom:28px}.eyebrow{margin:0 0 8px;text-transform:uppercase;font-size:12px;font-weight:700;letter-spacing:0;opacity:.78}h1,h2,p{margin-top:0}.login-brand h1{font-size:44px;line-height:1.05;margin-bottom:16px}.intro{max-width:430px;color:rgba(255,255,255,.84);font-size:17px;line-height:1.6}.login-panel{display:flex;flex-direction:column;justify-content:center;gap:18px;padding:48px}.login-panel h2{margin-bottom:8px;font-size:28px}label{display:grid;gap:8px;color:var(--muted);font-size:13px;font-weight:700}input,select,button{font:inherit}input,select{width:100%;min-height:44px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);padding:0 14px;outline:0}input:focus,select:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(22,78,159,.14)}button,.user-box a{border:0;border-radius:6px;background:var(--blue);color:#fff;min-height:44px;padding:0 18px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center}.hint{color:var(--muted);font-size:13px}.error{margin:0;color:var(--red);font-weight:700}.topbar{min-height:92px;display:flex;justify-content:space-between;align-items:center;gap:20px;padding:18px 28px;background:#fff;border-bottom:1px solid var(--line)}.brand{display:flex;align-items:center;gap:16px;min-width:0}.brand-logo{width:58px;height:58px;object-fit:contain}.brand h1{margin:0;font-size:24px;line-height:1.2}.brand .eyebrow{color:var(--red)}.user-box{display:flex;align-items:center;gap:12px;color:var(--muted);font-weight:700}.user-box a{min-height:38px;background:var(--red)}.developer-menu{position:relative;display:inline-flex}.developer-button{width:38px;min-height:38px;padding:0;border-radius:50%;background:var(--gold);color:#172033;font-size:18px}.developer-card{display:none;position:absolute;right:0;top:46px;width:270px;padding:16px;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 18px 45px rgba(15,23,42,.18);z-index:5}.developer-menu:focus-within .developer-card,.developer-menu:hover .developer-card{display:block}.developer-card strong{display:block;color:var(--blue);font-size:16px}.developer-card span{display:block;margin-top:6px;color:var(--muted);font-size:13px;line-height:1.45}.workspace{width:min(1500px,100%);margin:0 auto;padding:24px}.toolbar{display:grid;grid-template-columns:minmax(260px,1fr) 220px 96px;gap:12px;margin-bottom:16px}.search-wrap{position:relative}.search-wrap input{min-height:52px;padding-left:44px;font-size:16px}.search-icon{position:absolute;left:16px;top:50%;transform:translateY(-50%);color:var(--blue);font-size:22px}.summary-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}.summary-grid div{border:1px solid var(--line);background:#fff;border-radius:8px;padding:16px}.summary-grid span{display:block;color:var(--blue);font-size:22px;font-weight:800;overflow-wrap:anywhere}.summary-grid strong{display:block;margin-top:5px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:0}.sheet-pills{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}.sheet-pills button{min-height:34px;color:var(--ink);background:#fff;border:1px solid var(--line);font-size:13px}.sheet-pills button.active{color:#fff;background:var(--blue);border-color:var(--blue)}.table-shell{overflow:hidden;background:#fff;border:1px solid var(--line);border-radius:8px}.table-status{min-height:44px;display:flex;align-items:center;padding:0 16px;border-bottom:1px solid var(--line);color:var(--muted);font-weight:700}.table-scroll{max-height:calc(100vh - 310px);overflow:auto}table{width:100%;border-collapse:collapse;min-width:900px}th,td{padding:11px 12px;border-bottom:1px solid #e8edf4;border-right:1px solid #eef2f7;text-align:left;vertical-align:top;font-size:13px;line-height:1.45}th{position:sticky;top:0;z-index:1;background:#f8fafc;color:#334155;font-size:12px;text-transform:uppercase;letter-spacing:0}tbody tr:hover{background:#fff9e8}.empty{padding:36px 16px;text-align:center;color:var(--muted)}@media(max-width:760px){.login-shell{grid-template-columns:1fr}.login-brand,.login-panel{padding:32px}.login-brand h1{font-size:34px}.topbar{align-items:flex-start;flex-direction:column}.toolbar,.summary-grid{grid-template-columns:1fr}.workspace{padding:16px}.table-scroll{max-height:calc(100vh - 430px)}}
'''

JS = r'''
const searchInput=document.getElementById("searchInput"),sheetSelect=document.getElementById("sheetSelect"),clearButton=document.getElementById("clearButton"),table=document.getElementById("resultsTable"),statusText=document.getElementById("statusText"),fileName=document.getElementById("fileName"),resultCount=document.getElementById("resultCount"),totalCount=document.getElementById("totalCount"),sheetPills=document.getElementById("sheetPills");let activeSheet="all",timer=null;function esc(v){return String(v??"").replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]})}function renderSheets(sheets){const values=["all"].concat(sheets.map(function(s){return s.name}));const current=Array.from(sheetSelect.options).map(function(o){return o.value});if(JSON.stringify(values)!==JSON.stringify(current)){sheetSelect.innerHTML='<option value="all">All sheets</option>'+sheets.map(function(s){return '<option value="'+esc(s.name)+'">'+esc(s.name)+'</option>'}).join("");sheetSelect.value=activeSheet}sheetPills.innerHTML=[{name:"all",label:"All sheets"}].concat(sheets.map(function(s){return {name:s.name,label:s.name+" ("+Number(s.count).toLocaleString()+")"}})).map(function(s){return '<button type="button" data-sheet="'+esc(s.name)+'" class="'+(s.name===activeSheet?"active":"")+'">'+esc(s.label)+'</button>'}).join("");sheetPills.querySelectorAll("button").forEach(function(b){b.addEventListener("click",function(){activeSheet=b.dataset.sheet;sheetSelect.value=activeSheet;search()})})}function renderTable(data){const cols=data.columns||[],rows=data.rows||[],thead=table.querySelector("thead"),tbody=table.querySelector("tbody");thead.innerHTML=cols.length?"<tr>"+cols.map(function(c){return "<th>"+esc(c)+"</th>"}).join("")+"</tr>":"";tbody.innerHTML=rows.length?rows.map(function(r){return "<tr>"+cols.map(function(c){return "<td>"+esc(r[c]||"")+"</td>"}).join("")+"</tr>"}).join(""):"<tr><td class=\"empty\" colspan=\""+Math.max(cols.length,1)+"\">No records to display</td></tr>"}function renderStatus(data){fileName.textContent=data.file||"No workbook";resultCount.textContent=Number(data.result_count||0).toLocaleString();totalCount.textContent=Number(data.total_matches||0).toLocaleString();statusText.textContent=data.limited?"Showing first "+Number(data.max_results).toLocaleString()+" matching records. Add keywords to narrow results.":data.total_matches===0?"No matching records found.":"Records are filtered automatically as you type."}async function search(){const params=new URLSearchParams({q:searchInput.value.trim(),sheet:activeSheet});statusText.textContent="Filtering records...";try{const response=await fetch("/api/search?"+params.toString());if(!response.ok)throw new Error("Search failed");const data=await response.json();renderSheets(data.sheets||[]);renderStatus(data);renderTable(data)}catch(e){statusText.textContent="Unable to load the workbook. Please check the data folder.";table.querySelector("thead").innerHTML="";table.querySelector("tbody").innerHTML='<tr><td class="empty">Workbook could not be loaded.</td></tr>'}}searchInput.addEventListener("input",function(){clearTimeout(timer);timer=setTimeout(search,220)});sheetSelect.addEventListener("change",function(){activeSheet=sheetSelect.value;search()});clearButton.addEventListener("click",function(){searchInput.value="";searchInput.focus();search()});search();
'''


def page_login(message=""):
    logo = "/logo" if logo_file() else ""
    logo_html = f'<img src="{logo}" alt="PSA logo" class="login-logo">' if logo else ""
    error = f'<p class="error">{html.escape(message)}</p>' if message else ""
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>PSA Search Login</title><style>{CSS}</style></head><body class="login-body"><main class="login-shell"><section class="login-brand">{logo_html}<p class="eyebrow">Philippine Statistics Authority</p><h1>PSA Search System</h1><p class="intro">Secure local access for searching the PSOC and PSIC workbook records.</p></section><form class="login-panel" method="post" action="/login"><h2>Sign in</h2><label>Username<input name="username" autocomplete="username" required autofocus></label><label>Password<input name="password" type="password" autocomplete="current-password" required></label>{error}<button type="submit">Log in</button></form></main></body></html>'''


def page_app(username):
    logo = "/logo" if logo_file() else ""
    logo_html = f'<img src="{logo}" alt="PSA logo" class="brand-logo">' if logo else ""
    user = html.escape(username)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>PSA Search System</title><style>{CSS}</style></head><body><header class="topbar"><div class="brand">{logo_html}<div><p class="eyebrow">PSA Search System</p><h1>PSOC and PSIC Data Search</h1></div></div><div class="user-box"><div class="developer-menu"><button class="developer-button" type="button" aria-label="View developer information">i</button><div class="developer-card" role="status"><strong>Claverson Romuar</strong><span>Registration Kit Operator (National ID)</span></div></div><span>{user}</span><a href="/logout">Logout</a></div></header><main class="workspace"><section class="toolbar"><div class="search-wrap"><span class="search-icon">&#128269;</span><input id="searchInput" type="search" placeholder="Type keywords to auto-filter records" autocomplete="off"></div><select id="sheetSelect" aria-label="Sheet filter"><option value="all">All sheets</option></select><button id="clearButton" type="button">Clear</button></section><section class="summary-grid"><div><span id="fileName">Loading workbook...</span><strong>Source file</strong></div><div><span id="resultCount">0</span><strong>Results shown</strong></div><div><span id="totalCount">0</span><strong>Total matches</strong></div></section><section class="sheet-pills" id="sheetPills"></section><section class="table-shell"><div class="table-status" id="statusText">Loading records...</div><div class="table-scroll"><table id="resultsTable"><thead></thead><tbody></tbody></table></div></section></main><script>{JS}</script></body></html>'''


def send_html(handler, body, status=HTTPStatus.OK):
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def send_json(handler, payload, status=HTTPStatus.OK):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def redirect(handler, location):
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", location)
    handler.end_headers()


def get_cookie(cookie_header, name):
    for part in (cookie_header or "").split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            if key == name:
                return value
    return ""


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, format_string, *args):
        return

    def user(self):
        session = get_session(get_cookie(self.headers.get("Cookie"), SESSION_COOKIE))
        return session["username"] if session else ""

    def require_user(self):
        username = self.user()
        if not username:
            redirect(self, "/login")
        return username

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            redirect(self, "/") if self.user() else send_html(self, page_login())
            return
        if parsed.path == "/logout":
            username = self.user()
            token = get_cookie(self.headers.get("Cookie"), SESSION_COOKIE)
            clear_session(token)
            if username:
                write_log("logout", username)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")
            self.end_headers()
            return
        if parsed.path == "/logo":
            self.send_logo()
            return
        username = self.require_user()
        if not username:
            return
        if parsed.path == "/":
            send_html(self, page_app(username))
            return
        if parsed.path == "/api/search":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            sheet = params.get("sheet", ["all"])[0]
            try:
                payload = search_data(sheet, query)
                write_log("search", username, f"sheet={sheet}; query={query}; matches={payload['total_matches']}")
                send_json(self, payload)
            except Exception as exc:
                write_log("error", username, str(exc))
                send_json(self, {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        send_html(self, "Not found", HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if urlparse(self.path).path != "/login":
            send_html(self, "Not found", HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"))
        username = fields.get("username", [""])[0].strip()
        password = fields.get("password", [""])[0]
        if check_login(username, password):
            token = create_session(username)
            write_log("login_success", username)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_SECONDS}")
            self.end_headers()
        else:
            write_log("login_failed", username or "-")
            send_html(self, page_login("Invalid username or password."), HTTPStatus.UNAUTHORIZED)

    def send_logo(self):
        path = logo_file()
        if not path:
            send_html(self, "Logo not found", HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    ensure_files()
    print(f"PSA Search System is running at http://{HOST}:{PORT}")
    print("Default admin account is configured locally.")
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
