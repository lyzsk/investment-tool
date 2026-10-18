# -*- coding: utf-8 -*-
"""req_guard.py — 统一请求层 Python 版(10/15 建; 与 req_guard.mjs 接口一致、共读 req_guard_sources.json、共用 downloads/_guard/ 状态)
用法:
    from req_guard import gfetch, gcall, guard, ReqError, FAIL
    r = gfetch(url, headers={...}, timeout=10)      # urllib 实现, 返回 Resp(status/headers/content/text()/json()); HTTP 4xx/5xx 不抛(与 fetch 同语义)
    v = gcall(url, lambda: requests.get(url))        # 非 urllib 的请求(requests/pytdx 等): 守卫做前置+异常分类记账(异常原样抛)
    guard("cls").fail(FAIL.PARSE, "...")             # 业务层失败记账; .ban(info) 手动熔断
语义见 req_guard.mjs 文件头(熔断/日预算/滑动窗口/间隔/封禁特征/连败/探测解除/REQ_GUARD_PROBE)。
CLI: python req_guard.py --status | --clear <id> | --route <url>
"""
import datetime as dt, json, os, random, re, sys, time, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
GUARD_DIR = (HERE / ".." / ".." / "downloads" / "_guard").resolve()
CONF = json.loads((HERE / "req_guard_sources.json").read_text(encoding="utf-8"))


class FAIL:
    BLOCKED, AUTH, RATE_LIMIT, NO_DATA, UNAVAILABLE, PARSE = "BLOCKED", "AUTH", "RATE_LIMIT", "NO_DATA", "UNAVAILABLE", "PARSE"


STREAK = {FAIL.BLOCKED, FAIL.UNAVAILABLE, FAIL.RATE_LIMIT}


class ReqError(Exception):
    def __init__(self, kind, msg, **extra):
        super().__init__(f"[{kind}] {msg}")
        self.kind = kind
        self.__dict__.update(extra)


def _today():
    return dt.date.today().isoformat()


def _iso(ts=None):
    return dt.datetime.fromtimestamp(ts or time.time(), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_iso(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.timezone.utc).timestamp()
    except Exception:  # noqa: BLE001
        return 0


def _rd(f, d):
    try:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def _wr(f, obj):
    try:
        GUARD_DIR.mkdir(parents=True, exist_ok=True)
        tmp = f"{f}.{os.getpid()}.tmp"
        Path(tmp).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        try:
            os.replace(tmp, f)
        except OSError:
            Path(f).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:  # noqa: BLE001  记账失败不挡请求
        pass


def _probe_allowed(i):
    p = os.environ.get("REQ_GUARD_PROBE", "").split(",")
    return "all" in p or i in p


def classify(status=0, text="", err=None, cfg=None):
    cfg = cfg or CONF["_default"]
    if err is not None:
        m = f"{err} {getattr(err, 'code', '')} {type(err).__name__}"
        if isinstance(err, urllib.error.HTTPError):
            return classify(status=err.code, text=text, cfg=cfg)
        hs = re.search(r"HTTP (\d{3})", m)
        if hs:
            return classify(status=int(hs.group(1)), text=text, cfg=cfg)
        if isinstance(err, (ValueError,)) and ("JSON" in m or "Expecting" in m):
            return {"kind": FAIL.PARSE}
        return {"kind": FAIL.UNAVAILABLE}
    if status in (cfg.get("banStatus") or []):
        return {"kind": FAIL.BLOCKED, "ban": True, "why": f"HTTP {status}"}
    hit = next((p for p in (cfg.get("banBody") or []) if text and p in text), None)
    if hit:
        return {"kind": FAIL.BLOCKED, "ban": True, "why": f"命中封禁特征 {hit}"}
    if status == 401:
        return {"kind": FAIL.AUTH}
    if status in (403, 412):
        return {"kind": FAIL.BLOCKED}
    if status == 429:
        return {"kind": FAIL.RATE_LIMIT}
    if status in (404, 204):
        return {"kind": FAIL.NO_DATA}
    if status >= 400 or status == 0:
        return {"kind": FAIL.UNAVAILABLE}
    return None


class Resp:
    def __init__(self, status, headers, content, url):
        self.status, self.headers, self.content, self.url = status, headers, content, url
        self.ok = 200 <= status < 300

    def text(self, encoding="utf-8"):
        return self.content.decode(encoding, errors="replace")

    def json(self, encoding="utf-8"):
        return json.loads(self.text(encoding))


class Guard:
    def __init__(self, gid, cfg):
        self.id, self.cfg = gid, cfg
        self.f_ban = GUARD_DIR / f"{gid}.ban.json"
        self.f_state = GUARD_DIR / f"{gid}.state.json"

    @property
    def f_count(self):
        return GUARD_DIR / f"{self.id}_requests_{_today()}.json"

    def banned(self):
        b = _rd(self.f_ban, None)
        return b if b and _parse_iso(b.get("until", "")) > time.time() else None

    def _count(self, fn):
        c = _rd(self.f_count, None) or {"id": self.id, "date": _today(), "n": 0, "ok": 0, "fail": {}}
        fn(c)
        c["budget"], c["lastAt"] = self.cfg["dayBudget"], _iso()
        _wr(self.f_count, c)
        return c

    def _pre(self, max_wait_ms=None):
        b = self.banned()
        if b and not _probe_allowed(self.id):
            raise ReqError(FAIL.BLOCKED, f"{self.id} 熔断中({b.get('kind')}: {b.get('info')}) 至 {b.get('until')}, 不发请求", source=self.id, local=True)
        c = _rd(self.f_count, {"n": 0})
        if c.get("n", 0) >= self.cfg["dayBudget"]:
            raise ReqError(FAIL.RATE_LIMIT, f"{self.id} 今日请求 {c['n']} 已达预算 {self.cfg['dayBudget']}", source=self.id, local=True)
        max_wait = self.cfg["maxWaitMs"] if max_wait_ms is None else max_wait_ms
        for loop in range(60):
            st, now = _rd(self.f_state, {}), time.time() * 1000
            wait = 0
            if self.cfg.get("gapMs"):
                j = self.cfg["jitter"]
                gap = self.cfg["gapMs"] * (1 - j + random.random() * 2 * j)
                wait = max(wait, st.get("lastAt", 0) + gap - now)
            win = [t for t in st.get("win", []) if t > now - self.cfg.get("winSec", 0) * 1000]
            if self.cfg.get("winN") and len(win) >= self.cfg["winN"]:
                wait = max(wait, win[0] + self.cfg["winSec"] * 1000 - now + 50)
            if wait <= 0 or loop > 50:
                st["lastAt"] = now
                if self.cfg.get("winN"):
                    st["win"] = win + [now]
                _wr(self.f_state, st)
                break
            if wait > max_wait:
                raise ReqError(FAIL.RATE_LIMIT, f"{self.id} 限速: 需等 {wait / 1000:.0f}s > 上限 {max_wait / 1000:.0f}s, 本次不发", source=self.id, local=True)
            time.sleep(min(wait, 5000) / 1000)
        self._count(lambda x: x.__setitem__("n", x.get("n", 0) + 1))

    def ok(self):
        self._count(lambda x: x.__setitem__("ok", x.get("ok", 0) + 1))
        st = _rd(self.f_state, {})
        if st.get("streak"):
            st["streak"] = 0
            _wr(self.f_state, st)
        if self.f_ban.exists():
            b = _rd(self.f_ban, {})
            try:
                with open(GUARD_DIR / "ban_history.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({**b, "cleared": _iso()}, ensure_ascii=False) + "\n")
                self.f_ban.unlink()
            except OSError:
                pass

    def fail(self, kind, info="", ban=False, cool_min=None):
        def upd(x):
            x.setdefault("fail", {})[kind] = x.get("fail", {}).get(kind, 0) + 1
            x["lastFail"] = f"{kind} {str(info)[:160]}"
        self._count(upd)
        if ban:
            return self.ban(info, cool_min if cool_min is not None else self.cfg["banCoolMin"], kind)
        if kind not in STREAK:
            return
        st = _rd(self.f_state, {})
        st["streak"] = st.get("streak", 0) + 1
        _wr(self.f_state, st)
        if st["streak"] >= self.cfg["breakN"]:
            self.ban(f"连败 {st['streak']} 次, 末次 {kind} {info}", cool_min if cool_min is not None else self.cfg["coolMin"], kind)

    def ban(self, info="", cool_min=None, kind=FAIL.BLOCKED):
        m = self.cfg["banCoolMin"] if cool_min is None else cool_min
        now = time.time()
        c = _rd(self.f_count, {"n": 0})
        _wr(self.f_ban, {"id": self.id, "kind": kind, "info": str(info)[:200], "at": _iso(now), "until": _iso(now + m * 60), "coolMin": m, "reqToday": c.get("n", 0)})
        st = _rd(self.f_state, {})
        st["streak"] = 0
        _wr(self.f_state, st)
        print(f"[req_guard] {self.id} 熔断 {m} 分钟: {kind} {str(info)[:120]}", file=sys.stderr)

    def fetch(self, url, headers=None, data=None, method=None, timeout=None, max_wait_ms=None):
        self._pre(max_wait_ms)
        req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.cfg["timeoutMs"] / 1000) as r:
                resp = Resp(r.status, dict(r.headers), r.read(), url)
        except urllib.error.HTTPError as e:
            resp = Resp(e.code, dict(e.headers or {}), e.read() if hasattr(e, "read") else b"", url)
        except Exception as e:  # noqa: BLE001
            k = classify(err=e, cfg=self.cfg)
            self.fail(k["kind"], f"{e} {url[:80]}")
            raise
        text = ""
        ct = resp.headers.get("Content-Type", "") or resp.headers.get("content-type", "")
        if not resp.ok or (self.cfg.get("banBody") and (not ct or re.search(r"json|text|html|javascript|xml", ct, re.I))):
            text = resp.content[:200000].decode("utf-8", errors="replace")
        k = classify(status=resp.status, text=text, cfg=self.cfg)
        if not k:
            self.ok()
            return resp
        self.fail(k["kind"], f"{k.get('why') or 'HTTP %d' % resp.status} {url[:80]}", ban=bool(k.get("ban")))
        if k.get("ban"):
            raise ReqError(FAIL.BLOCKED, f"{self.id} {k.get('why')}: {re.sub(r'<[^>]+>', ' ', text)[:100]}", source=self.id, status=resp.status)
        return resp

    def call(self, fn, url="", max_wait_ms=None):
        self._pre(max_wait_ms)
        try:
            v = fn()
        except Exception as e:  # noqa: BLE001
            k = classify(err=e, cfg=self.cfg)
            self.fail(k["kind"], f"{e} {url[:80]}", ban=bool(k.get("ban")))
            raise
        self.ok()
        return v


_CACHE = {}


def guard(gid, **override):
    if override:
        return Guard(gid, {**CONF["_default"], **CONF["sources"].get(gid, {}), **override})
    if gid not in _CACHE:
        _CACHE[gid] = Guard(gid, {**CONF["_default"], **CONF["sources"].get(gid, {})})
    return _CACHE[gid]


def source_of(url):
    u = urlparse(url)
    host = u.hostname or ""
    hp = host + (u.path or "")
    best = None
    for gid, c in CONF["sources"].items():
        for h in c.get("hosts", []):  # 含 "/" = 域名+路径前缀(同域不同接口分开熔断)
            hit = hp.startswith(h) if "/" in h else ((host.endswith(h) or host == h[1:]) if h.startswith(".") else host == h)
            if hit and (best is None or len(h) > best[1]):
                best = (gid, len(h))
    return best[0] if best else "_other"


def gfetch(url, source=None, **kw):
    return guard(source or source_of(url)).fetch(url, **kw)


def gcall(url, fn, source=None, **kw):
    return guard(source or source_of(url)).call(fn, url=url, **kw)


def guard_status():
    out = {"bans": [], "counters": []}
    if not GUARD_DIR.exists():
        return out
    for f in GUARD_DIR.iterdir():
        if f.name.endswith(".ban.json"):
            b = _rd(f, None)
            if b:
                out["bans"].append({**b, "active": _parse_iso(b.get("until", "")) > time.time()})
        m = re.match(r"^(.+)_requests_(\d{4}-\d\d-\d\d)\.json$", f.name)
        if m and m.group(2) == _today():
            out["counters"].append(_rd(f, {}))
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--clear"] and len(a) > 1:
        g = guard(a[1])
        if g.f_ban.exists():
            with open(GUARD_DIR / "ban_history.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({**_rd(g.f_ban, {}), "cleared": _iso(), "by": "manual"}, ensure_ascii=False) + "\n")
            g.f_ban.unlink()
        print(f"cleared {a[1]}")
    elif a[:1] == ["--route"] and len(a) > 1:
        print(source_of(a[1]))
    else:
        print(json.dumps(guard_status(), ensure_ascii=False, indent=1))
