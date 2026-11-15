"""Run the personal timetable on the local computer."""

import argparse
import json
import re
import sqlite3
import sys
import threading
import uuid
import webbrowser
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, time, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

from calendar_extract import extract_events
from calendar_voice import parse_schedule

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
CATEGORIES = {"assignment", "activity", "life"}
ORIGINS = {"manual", "voice"}
ASSETS = {
    "/": ("index.html", "text/html"),
    "/index.html": ("index.html", "text/html"),
    "/style.css": ("style.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
    "/favicon.ico": ("calendar.ico", "image/x-icon"),
}
EVENT_PATH = re.compile(r"/api/events/([0-9a-f]{32})")


def current_time():
    return datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)


def monday_of(day):
    return day - timedelta(days=day.weekday())


def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("请选择有效的日期。")
    return date.fromisoformat(value)


def field(data, key, limit, default=""):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError("请检查输入内容的格式和长度。")
    return value.strip()


def event_time(value, all_day):
    if all_day:
        return parse_date(value).isoformat()
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::[0-9]{2})?", value
    ):
        raise ValueError("请选择有效的日期和时间。")
    parsed = datetime.fromisoformat(value)
    return parsed.isoformat(timespec="seconds" if parsed.second else "minutes")


def validate_event(data):
    title = field(data, "title", 200)
    if not title:
        raise ValueError("请填写日程标题。")
    category = field(data, "category", 20, "life")
    origin = field(data, "origin", 20, "manual")
    kind = field(data, "kind", 20, "event")
    if category not in CATEGORIES or origin not in ORIGINS:
        raise ValueError("请选择有效的日程分类。")
    if kind not in {"event", "deadline", "notice"}:
        raise ValueError("请选择有效的日程类型。")
    all_day = data.get("all_day", False)
    if type(all_day) is not bool:
        raise ValueError("请检查全天选项。")
    start = event_time(data.get("start"), all_day)
    end_value = data.get("end")
    end = event_time(end_value, all_day) if end_value not in (None, "") else None
    if end is not None:
        if all_day and end < start:
            raise ValueError("结束日期不能早于开始日期。")
        if not all_day and datetime.fromisoformat(end) <= datetime.fromisoformat(start):
            raise ValueError("结束时间须晚于开始时间。")
    return {
        "title": title, "category": category, "origin": origin, "kind": kind,
        "start": start, "end": end, "all_day": all_day,
        "location": field(data, "location", 200), "notes": field(data, "notes", 5000),
        "source_date": "", "source_url": "", "mail_url": "", "status": "planned",
    }


def in_range(event, first, limit):
    start = event["start"]
    if start >= limit.isoformat():
        return False
    end = event.get("end")
    if end is None or event["all_day"]:
        return (end or start)[:10] >= first.isoformat()
    return datetime.fromisoformat(end) > datetime.combine(first, time())


class Schedule:
    def __init__(self, root, database, *, demo=False):
        self.diary = root / "每日记录.md"
        self.checkpoint = root / "每日记录状态.json"
        self.database = database
        self.demo = demo
        self.cache_lock = threading.Lock()
        self.cached_diary = None
        self.cached_events = []
        database.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def imported(self, today):
        try:
            contents = self.diary.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            with self.cache_lock:
                return self.cached_events, "每日记录暂时无法读取。"
        with self.cache_lock:
            key = (today, contents)
            if key != self.cached_diary:
                self.cached_events = extract_events(contents, today)
                self.cached_diary = key
            return self.cached_events, None

    def mail_status(self, warning):
        if self.demo:
            return {"demo": True, "warning": warning}
        try:
            data = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("Invalid checkpoint")
        except (OSError, ValueError):
            return {"last_success_at": None, "coverage_end": None,
                    "warning": warning or "邮件检查时间暂时不可用。"}
        coverage = data.get("last_success_coverage") or {}
        attempt_status = data.get("last_attempt_status")
        if not warning and attempt_status in ("failure", "failed", "error"):
            warning = "最近一次 Gmail 检查失败，课表仍显示已同步的事项。"
        return {
            "last_success_at": data.get("last_success_at"),
            "coverage_end": coverage.get("end_exclusive") if isinstance(coverage, dict) else None,
            "last_attempt_status": attempt_status,
            "warning": warning,
        }

    def listing(self, params):
        today = current_time().date()
        week = monday_of(parse_date(params["week"][0]) if "week" in params else today)
        first = parse_date(params["from"][0]) if "from" in params else week
        limit = parse_date(params["to"][0]) if "to" in params else first + timedelta(days=7)
        if not 0 < (limit - first).days <= 93:
            raise ValueError("请选择 1 至 93 天的日期范围。")
        imported, warning = self.imported(today)
        with self.connection() as db:
            manual = [json.loads(row[0]) for row in db.execute("SELECT payload FROM events")]
        events = [event for event in (*imported, *manual) if in_range(event, first, limit)]
        events.sort(key=lambda e: (e["start"], not e["all_day"], e["title"]))
        return {"week": week.isoformat(), "today": today.isoformat(), "timezone": SHANGHAI.tzname(None),
                "events": events, "mail": self.mail_status(warning)}

    def create(self, data):
        event = validate_event(data)
        event["id"] = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("INSERT INTO events VALUES (?, ?)", (event["id"], json.dumps(event, ensure_ascii=False)))
        return event

    def update(self, event_id, data):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM events WHERE id = ?", (event_id,)).fetchone()
            if row is None:
                raise LookupError
            current = json.loads(row[0])
            event = validate_event({**current, **data, "origin": current["origin"]})
            event["id"] = event_id
            db.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(event, ensure_ascii=False), event_id))
        return event

    def delete(self, event_id):
        with self.connection() as db:
            if not db.execute("DELETE FROM events WHERE id = ?", (event_id,)).rowcount:
                raise LookupError


class RequestHandler(BaseHTTPRequestHandler):
    def respond(self, code, data, content_type="application/json"):
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        if content_type.startswith(("text/", "application/json")):
            content_type += "; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("请以 JSON 提交日程。")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 32768:
            raise ValueError("请求内容为空或过长。")
        try:
            data = json.loads(self.rfile.read(length))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("无法读取日程数据。") from exc
        if not isinstance(data, dict):
            raise ValueError("请提交一份日程数据。")
        return data

    def handle_request(self, method):
        host = self.headers.get("Host", "")
        local_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        if host not in local_hosts or (origin and origin != f"http://{host}"):
            self.respond(HTTPStatus.FORBIDDEN, {"error": "请通过本机地址访问日程。"})
            return
        schedule = self.server.schedule
        try:
            url = urlsplit(self.path)
            path = url.path
            if method == "GET" and path in ASSETS:
                filename, content_type = ASSETS[path]
                self.respond(HTTPStatus.OK, (WEB / filename).read_bytes(), content_type)
            elif method == "GET" and path == "/api/schedule":
                self.respond(HTTPStatus.OK, schedule.listing(parse_qs(url.query)))
            elif method == "POST" and path == "/api/parse":
                body = self.body()
                transcript = field(body, "text", 1000)
                if not transcript:
                    raise ValueError("请说出或输入要添加的日程。")
                base = current_time()
                if body.get("base_date"):
                    base = datetime.combine(parse_date(body["base_date"]), base.time())
                self.respond(HTTPStatus.OK, parse_schedule(transcript, base))
            elif method == "POST" and path == "/api/events":
                self.respond(HTTPStatus.CREATED, {"event": schedule.create(self.body())})
            elif method in {"PATCH", "DELETE"} and (match := EVENT_PATH.fullmatch(path)):
                event_id = match[1]
                if method == "PATCH":
                    self.respond(HTTPStatus.OK, {"event": schedule.update(event_id, self.body())})
                else:
                    schedule.delete(event_id)
                    self.respond(HTTPStatus.OK, {"deleted": True})
            else:
                raise LookupError
        except (LookupError, FileNotFoundError):
            self.respond(HTTPStatus.NOT_FOUND, {"error": "未找到该日程或页面。"})
        except (ValueError, OverflowError) as exc:
            self.respond(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (OSError, sqlite3.Error) as exc:
            self.log_error("%s", str(exc))
            self.respond(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "无法读写本机日程，请重试。"})

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PATCH(self):
        self.handle_request("PATCH")

    def do_DELETE(self):
        self.handle_request("DELETE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the timetable in your default browser")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--data-dir", type=Path, default=ROOT, help="Directory containing the local diary")
    source.add_argument("--demo", action="store_true", help="Use a temporary diary with fictional events")
    args = parser.parse_args()
    try:
        with (TemporaryDirectory(prefix="calendar-demo-") if args.demo else nullcontext(args.data_dir)) as directory:
            data_dir = Path(directory)
            if args.demo:
                template = (ROOT / "examples" / "diary.example.md").read_text(encoding="utf-8")
                dated = re.sub(r"(?m)^# \d{4}-\d{2}-\d{2}$", f"# {current_time().date().isoformat()}", template, count=1)
                (data_dir / "每日记录.md").write_text(dated, encoding="utf-8")
            schedule = Schedule(data_dir, data_dir / ".dailyhelper" / "schedule.sqlite3", demo=args.demo)
            with ThreadingHTTPServer(("127.0.0.1", args.port), RequestHandler) as server:
                server.schedule = schedule
                url = f"http://127.0.0.1:{server.server_port}"
                print(f"日程已启动 {url}", flush=True)
                if args.open:
                    webbrowser.open(url)
                server.serve_forever()
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"日程启动失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
