#!/usr/bin/env python3
"""Local DSH Agent bridge for 巴小卡 nl-analyze. No keys logged. Listens 127.0.0.1:8789."""
from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DSH_HOST = os.environ.get("DSH_BRIDGE_DSH_HOST", "127.0.0.1")
DSH_PORT = int(os.environ.get("DSH_BRIDGE_DSH_PORT", "8788"))
LISTEN = os.environ.get("DSH_BRIDGE_LISTEN", "127.0.0.1")
PORT = int(os.environ.get("DSH_BRIDGE_PORT", "8789"))
DEFAULT_TIMEOUT_S = int(os.environ.get("DSH_BRIDGE_TIMEOUT_S", "360"))
COOKIE_PATH = os.environ.get("DSH_BRIDGE_COOKIE_PATH", "/root/.dsh/dsh-web.cookie")
# switched default model to deepseek-v4.1-flash (was gpt-6-astra)
DEFAULT_PROVIDER = os.environ.get("DSH_BRIDGE_PROVIDER", "deepseek-official")
DEFAULT_MODEL = os.environ.get("DSH_BRIDGE_MODEL", "deepseek-v4.1-flash")
DEFAULT_EFFORT = os.environ.get("DSH_BRIDGE_REASONING", "off")

_lock = threading.Lock()
_cookie: str | None = None

# In-memory async jobs for phone-safe short-polling (POST returns immediately).
_jobs_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_JOB_TTL_S = int(os.environ.get("DSH_BRIDGE_JOB_TTL_S", "3600"))


def _prune_jobs(now: float | None = None) -> None:
    now = time.time() if now is None else now
    with _jobs_lock:
        stale = [jid for jid, j in _jobs.items() if now - float(j.get("created_at") or 0) > _JOB_TTL_S]
        for jid in stale:
            _jobs.pop(jid, None)


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(fields)


def _run_job(job_id: str, query: str, timeout_s: int) -> None:
    _set_job(job_id, status="running", started_at=time.time())
    try:
        result = run_ask(query, timeout_s=timeout_s)
        _set_job(
            job_id,
            status="done" if result.get("ok") else "error",
            result=result,
            error=None if result.get("ok") else (result.get("error") or "ask failed"),
            finished_at=time.time(),
        )
    except Exception as e:
        _set_job(
            job_id,
            status="error",
            error=str(e)[:800],
            result=None,
            finished_at=time.time(),
        )


def create_job(query: str, timeout_s: int | None = None) -> dict:
    _prune_jobs()
    job_id = uuid.uuid4().hex
    timeout = int(timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S)
    # Backtests need ~300s+; clamp floor for async path
    if timeout < 360:
        timeout = 360
    job = {
        "job_id": job_id,
        "status": "queued",
        "query": query,
        "timeout_s": timeout,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
    }
    with _jobs_lock:
        _jobs[job_id] = job
    t = threading.Thread(target=_run_job, args=(job_id, query, timeout), daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id, "status": "queued", "timeout_s": timeout}


def get_job(job_id: str) -> dict | None:
    _prune_jobs()
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        # shallow copy for response (omit raw query optionally keep)
        out = {
            "ok": True,
            "job_id": job["job_id"],
            "status": job["status"],
            "query": job.get("query"),
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "timeout_s": job.get("timeout_s"),
            "error": job.get("error"),
            "result": job.get("result"),
        }
        return out


def _journal_token() -> str | None:
    try:
        j = subprocess.check_output(
            ["journalctl", "-u", "dsh-web", "-n", "20", "--no-pager"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None
    ms = re.findall(r"token=([A-Za-z0-9_-]+)", j)
    return ms[-1] if ms else None


def refresh_cookie(force: bool = False) -> str:
    global _cookie
    with _lock:
        if _cookie and not force and os.path.exists(COOKIE_PATH):
            return _cookie
        token = _journal_token()
        if not token:
            raise RuntimeError("dsh web launch token not found in journal")
        conn = http.client.HTTPConnection(DSH_HOST, DSH_PORT, timeout=20)
        conn.request("GET", f"/?token={token}", headers={"Host": f"{DSH_HOST}:{DSH_PORT}"})
        resp = conn.getresponse()
        resp.read()
        sc = resp.getheader("Set-Cookie")
        if resp.status != 303 or not sc:
            raise RuntimeError(f"token exchange failed HTTP {resp.status}")
        cookie = sc.split(";", 1)[0]
        _cookie = cookie
        try:
            with open(COOKIE_PATH, "w") as f:
                f.write(cookie + "\n")
            os.chmod(COOKIE_PATH, 0o600)
        except OSError:
            pass
        return cookie


def load_cookie() -> str:
    global _cookie
    if _cookie:
        return _cookie
    if os.path.exists(COOKIE_PATH):
        with open(COOKIE_PATH) as f:
            line = f.read().strip()
        if line:
            _cookie = line
            return line
    return refresh_cookie(force=True)


def dsh_rpc(endpoint: str, args: dict, timeout: int = 120, cookie: str | None = None) -> dict:
    cookie = cookie or load_cookie()
    rpc_id = str(uuid.uuid4())
    body = json.dumps(
        {"type": "client-request", "rpcId": rpc_id, "method": endpoint, "payload": {"args": args}}
    ).encode()
    conn = http.client.HTTPConnection(DSH_HOST, DSH_PORT, timeout=timeout)
    conn.request(
        "POST",
        f"/api/{endpoint}",
        body=body,
        headers={
            "content-type": "application/json",
            "Host": f"{DSH_HOST}:{DSH_PORT}",
            "Cookie": cookie,
            "Content-Length": str(len(body)),
        },
    )
    resp = conn.getresponse()
    raw = resp.read().decode("utf-8", "replace")
    if resp.status == 401:
        cookie = refresh_cookie(force=True)
        return dsh_rpc(endpoint, args, timeout=timeout, cookie=cookie)
    if resp.status != 200:
        raise RuntimeError(f"DSH {endpoint} HTTP {resp.status}: {raw[:300]}")
    data = json.loads(raw)
    result = data.get("result") or {}
    if not result.get("ok", True) and "error" in result:
        err = result["error"]
        raise RuntimeError(f"DSH {endpoint} error: {err.get('code')} {err.get('message')}")
    return data


def _text_from_content(content) -> list[str]:
    texts: list[str] = []
    if isinstance(content, str) and content.strip():
        texts.append(content.strip())
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text") or ""
                if t.strip():
                    texts.append(t.strip())
            elif isinstance(block, str) and block.strip():
                texts.append(block.strip())
    return texts


def extract_assistant_text(records: list) -> str:
    texts: list[str] = []
    for rec in records:
        if rec.get("type") != "event":
            continue
        ev = rec.get("event") or {}
        et = ev.get("type")
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        if et in ("assistant/message", "assistant/attempt", "assistant/text"):
            msg = data.get("message")
            if isinstance(msg, dict):
                texts.extend(_text_from_content(msg.get("content")))
            texts.extend(_text_from_content(data.get("content") or data.get("blocks")))
            if isinstance(data.get("text"), str) and data["text"].strip():
                texts.append(data["text"].strip())
    # prefer last non-empty join of unique consecutive blocks
    return "\n\n".join(texts).strip()


def extract_turn_error(records: list) -> str | None:
    for rec in reversed(records):
        if rec.get("type") != "event":
            continue
        ev = rec.get("event") or {}
        if ev.get("type") != "turn/end":
            continue
        data = ev.get("data") or {}
        reason = data.get("reason")
        if isinstance(reason, dict) and reason.get("kind") == "error":
            msg = reason.get("message") or reason.get("error") or json.dumps(reason, ensure_ascii=False)
            return str(msg)[:800]
        if reason == "error":
            return str(data.get("error") or data.get("message") or "turn ended with error")[:800]
        # nested error payloads
        err = data.get("error")
        if err:
            return str(err)[:800]
    return None


def run_ask(query: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
    started = time.time()
    created = dsh_rpc("session/create", {"request": {"cwd": "/root"}})
    sid = created["result"]["value"]["sessionId"]
    skills = dsh_rpc("skills/list", {"request": {"sessionId": sid}})
    skill_names = [s.get("name") for s in (skills["result"]["value"].get("skills") or [])]

    # Pin model for tu-zi (hot settings may already default here)
    try:
        dsh_rpc(
            "session/selectModel",
            {
                "request": {
                    "sessionId": sid,
                    "provider": DEFAULT_PROVIDER,
                    "model": DEFAULT_MODEL,
                    "reasoningEffort": DEFAULT_EFFORT,
                }
            },
        )
    except Exception as e:
        # non-fatal if settings already match; still try prompt
        model_err = str(e)
    else:
        model_err = None

    hint = (
        "请优先使用已安装的 quant-buddy-skill / quant-buddy-view。"
        "用 skill 工具链出数；最终给出可阅读的中文结论，含表格时用 markdown 表。"
        "不要渲染「来源」。不要调用 ask_user_question；遇 A/H 歧义默认 A 股。"
        "仅供观察，不构成投资建议。\n\n用户问题：\n"
    )
    prompt_text = hint + query
    dsh_rpc(
        "session/prompt",
        {
            "request": {
                "requestId": str(uuid.uuid4()),
                "sessionId": sid,
                "mode": "queue",
                "content": [{"type": "text", "text": prompt_text}],
                "clientTimeZone": "Asia/Shanghai",
            }
        },
    )

    deadline = started + timeout_s
    through_seq = 0
    final_text = ""
    last_error = model_err
    turn_error = None
    while time.time() < deadline:
        listed = dsh_rpc("session/list", {"_request": {}})
        items = listed["result"]["value"].get("items") or []
        mine = next((x for x in items if x.get("sessionId") == sid), None)
        if not mine:
            time.sleep(1.5)
            continue
        proj = (mine.get("projections") or {}).get("values") or {}
        as_of = (mine.get("projections") or {}).get("asOfSeq") or through_seq
        through_seq = max(through_seq, int(as_of))
        running = bool(mine.get("running"))
        outline = proj.get("turnOutline") or []
        response_hint = ""
        if outline:
            response_hint = (outline[-1] or {}).get("response") or ""

        try:
            page = dsh_rpc(
                "session/page",
                {
                    "request": {
                        "address": {"kind": "session", "sessionId": sid},
                        "throughSeq": through_seq,
                        "maxMessages": 200,
                    }
                },
            )
            records = page["result"]["value"].get("records") or []
            final_text = extract_assistant_text(records) or response_hint
            turn_error = extract_turn_error(records) or turn_error
        except Exception as e:
            last_error = str(e)
            if response_hint:
                final_text = response_hint

        if turn_error and not running:
            break
        if not running and final_text:
            break
        if not running and (proj.get("sessionStats") or {}).get("turns", 0) >= 1:
            break
        time.sleep(1.5)

    latency_ms = int((time.time() - started) * 1000)
    ok = bool(final_text) and not turn_error
    err = None
    if not ok:
        err = turn_error or last_error or "empty assistant output / timeout"
    return {
        "ok": ok,
        "session_id": sid,
        "skills": skill_names,
        "model": {"provider": DEFAULT_PROVIDER, "model": DEFAULT_MODEL},
        "text": final_text,
        "latency_ms": latency_ms,
        "error": err,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys_stderr = __import__("sys").stderr
        sys_stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code: int, obj: dict):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/health"):
            try:
                load_cookie()
                created = dsh_rpc("session/create", {"request": {}})
                sid = created["result"]["value"]["sessionId"]
                skills = dsh_rpc("skills/list", {"request": {"sessionId": sid}})
                names = [s.get("name") for s in (skills["result"]["value"].get("skills") or [])]
                skills_ok = "quant-buddy-skill" in names and "quant-buddy-view" in names
                with _jobs_lock:
                    job_count = len(_jobs)
                self._json(
                    200,
                    {
                        "ok": True,
                        "skills": names,
                        "skills_ok": skills_ok,
                        "model": {"provider": DEFAULT_PROVIDER, "model": DEFAULT_MODEL},
                        "jobs": job_count,
                    },
                )
            except Exception as e:
                self._json(503, {"ok": False, "error": str(e)})
            return
        # GET /v1/jobs/<job_id>
        m = re.match(r"^/v1/jobs/([A-Za-z0-9_-]+)/?$", path)
        if m:
            job = get_job(m.group(1))
            if not job:
                self._json(404, {"ok": False, "error": "job not found"})
                return
            self._json(200, job)
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except Exception:
            self._json(400, {"ok": False, "error": "invalid json"})
            return

        if path in ("/v1/jobs", "/jobs"):
            query = (body.get("query") or "").strip()
            if not query:
                self._json(400, {"ok": False, "error": "query required"})
                return
            timeout_s = body.get("timeout_s")
            try:
                timeout_s = int(timeout_s) if timeout_s is not None else None
            except Exception:
                self._json(400, {"ok": False, "error": "timeout_s must be int"})
                return
            try:
                created = create_job(query, timeout_s=timeout_s)
                self._json(202, created)
            except Exception as e:
                self._json(502, {"ok": False, "error": str(e)})
            return

        if path not in ("/v1/ask", "/ask"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        query = (body.get("query") or "").strip()
        if not query:
            self._json(400, {"ok": False, "error": "query required"})
            return
        timeout_s = int(body.get("timeout_s") or DEFAULT_TIMEOUT_S)
        try:
            result = run_ask(query, timeout_s=timeout_s)
            self._json(200 if result["ok"] else 504, result)
        except Exception as e:
            self._json(502, {"ok": False, "error": str(e)})


def main():
    try:
        refresh_cookie(force=True)
        print(
            f"dsh-bridge: cookie ready, listening {LISTEN}:{PORT} model={DEFAULT_PROVIDER}/{DEFAULT_MODEL}",
            flush=True,
        )
    except Exception as e:
        print(f"dsh-bridge: cookie warm failed ({e}); will retry on demand", flush=True)
    server = ThreadingHTTPServer((LISTEN, PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
