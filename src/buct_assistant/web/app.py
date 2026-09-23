# -*- coding: utf-8 -*-
"""本地网页控制台。只监听 127.0.0.1。

注意：上下文中所有 requests 调用都是同步的，必须放在线程里跑，
不要在 async 路由里直接调用（会阻塞事件循环）。
"""
import asyncio
import datetime
import json
import os
import re
import secrets
import threading

import yaml
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..core import classfilter
from ..core.service import Service
from ..logging_setup import setup as setup_logging
from ..notify import dispatcher as disp
from ..notify.dispatcher import TIER_LABEL, fmt_left
from ..platform.models import TZ
from ..settings import Settings
from ..submit_flow.manager import SubmitManager

HERE = os.path.dirname(os.path.abspath(__file__))
_lock = threading.Lock()


def _fmt_left(sec) -> str:
    if sec is None:
        return "—"
    return fmt_left(datetime.timedelta(seconds=sec))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    log = setup_logging(settings.logs_dir, quiet=True)
    svc = Service(settings, log)

    app = FastAPI(title="北化在线作业助手", docs_url="/api/docs")
    app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
    templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
    templates.env.filters["left"] = _fmt_left

    app.state.svc = svc
    app.state.submit = SubmitManager(settings, svc, log)
    app.state.scanning = False
    app.state.csrf = secrets.token_urlsafe(24)
    app.state.last_result = None

    # ---------- 页面 ----------
    @app.get("/", response_class=HTMLResponse)
    def index():
        return RedirectResponse("/dashboard")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        # Starlette 1.x 起签名是 TemplateResponse(request, name, context)
        return templates.TemplateResponse(request, "dashboard.html", {
            "csrf": app.state.csrf, "cfg": settings.notify_cfg,
            "deg": _degraded(svc)})

    @app.get("/homework/{course_id}/{hwtid}", response_class=HTMLResponse)
    def homework_page(request: Request, course_id: str, hwtid: str):
        rec = svc.state.get(f"{course_id}:{hwtid}") or {}
        return templates.TemplateResponse(request, "homework.html", {
            "csrf": app.state.csrf, "rec": rec,
            "course_id": course_id, "hwtid": hwtid})

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        return templates.TemplateResponse(request, "settings.html", {
            "csrf": app.state.csrf,
            "cfg_yaml": yaml.safe_dump(settings.raw, allow_unicode=True, sort_keys=False)})

    @app.get("/logs", response_class=HTMLResponse)
    def logs_page(request: Request):
        return templates.TemplateResponse(request, "logs.html", {
            "csrf": app.state.csrf})

    # ---------- 数据 ----------
    @app.get("/api/state")
    def api_state():
        return JSONResponse({**svc.dashboard_payload(),
                             "scanning": app.state.scanning,
                             "tier_labels": TIER_LABEL})

    @app.post("/api/scan")
    async def api_scan(request: Request):
        body = await request.json() if await request.body() else {}
        if body.get("csrf") != app.state.csrf:
            return JSONResponse({"ok": False, "err": "CSRF 校验失败"}, status_code=403)
        if app.state.scanning:
            return {"ok": False, "err": "已有扫描在进行"}
        started = _start_scan(svc, app)
        return {"ok": True, "started": started}

    @app.get("/api/events")
    async def api_events(request: Request):
        q = svc.board.subscribe()

        async def gen():
            try:
                for ev in svc.board.recent(20):
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=20)
                        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                svc.board.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/api/logs")
    def api_logs(tail: int = 200):
        path = os.path.join(settings.logs_dir, "app.log")
        if not os.path.exists(path):
            return {"lines": []}
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-max(1, min(tail, 2000)):]
        return {"lines": [ln.rstrip("\n") for ln in lines]}

    @app.get("/api/diagnostics")
    def api_diag():
        info = svc.last_scan_info
        return {
            "session_cached": svc._ps is not None,
            "login": svc.state.data.get("login", {}),
            "throttle_until": svc.state.data.get("throttle_until"),
            "last_scan": info,
            "homework_count": len(svc.state.data.get("homeworks", {})),
            "notifiers": [n.name for n in svc.build_notifiers() if n.enabled()],
            "degraded": _degraded(svc),
            "now": datetime.datetime.now(TZ).isoformat(timespec="seconds"),
        }

    @app.post("/api/diagnostics/relogin")
    async def api_relogin(request: Request):
        body = await request.json() if await request.body() else {}
        if body.get("csrf") != app.state.csrf:
            return JSONResponse({"ok": False, "err": "CSRF 校验失败"}, status_code=403)

        def work():
            # 真正的重新登录：作废内存会话并跳过 Cookie 复用，
            # 强制走一次全新的 CAS 登录（旧 Cookie 在新登录成功前不会丢失）
            svc.invalidate_session()
            try:
                svc.platform_session(force_login=True)
                return {"ok": True}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "err": str(e)}

        return await asyncio.to_thread(work)

    @app.post("/api/settings")
    async def api_save_settings(request: Request):
        body = await request.json()
        if body.get("csrf") != app.state.csrf:
            return JSONResponse({"ok": False, "err": "CSRF 校验失败"}, status_code=403)
        text = body.get("yaml", "")
        try:
            parsed = yaml.safe_load(text)
            assert isinstance(parsed, dict)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": f"YAML 解析失败: {e}"}
        path = os.path.join(settings.root, "config", "config.yaml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(parsed, f, allow_unicode=True, sort_keys=False)
        return {"ok": True, "note": "已保存，重启控制台后生效"}

    @app.post("/api/settings/class")
    async def api_save_class(request: Request):
        """班级过滤：独立入口，改完立即生效（不必重启）。"""
        body = await request.json()
        if body.get("csrf") != app.state.csrf:
            return JSONResponse({"ok": False, "err": "CSRF 校验失败"}, status_code=403)
        my_class = str(body.get("my_class") or "").strip()
        courses = [s.strip() for s in str(body.get("courses") or "").split(",") if s.strip()]
        enabled = bool(body.get("enabled"))

        path = os.path.join(settings.root, "config", "config.yaml")
        cfg = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        cf = cfg.setdefault("class_filter", {})
        cf.update({"enabled": enabled, "my_class": my_class, "courses": courses})
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        # 同步到内存，立即生效
        settings.raw.setdefault("class_filter", {}).update(
            {"enabled": enabled, "my_class": my_class, "courses": courses})
        log.info("班级过滤已更新: enabled=%s my_class=%r", enabled, my_class)
        return {"ok": True, "note": "已保存并立即生效"}

    @app.get("/api/settings/class")
    def api_get_class():
        c = settings.class_cfg
        return {"enabled": bool(c.get("enabled")), "my_class": c.get("my_class") or "",
                "courses": c.get("courses") or []}

    @app.get("/api/class/preview")
    def api_class_preview():
        """按当前配置试算一遍：会保留多少、会滤掉多少。"""
        svc.state.refresh()
        kept, dropped = [], []
        for rec in svc.state.data.get("homeworks", {}).values():
            show, code = classfilter.decide(rec.get("course_name", ""), rec.get("title", ""),
                                            settings.class_cfg)
            (kept if show else dropped).append(
                {"course": rec.get("course_name", ""), "title": rec.get("title", ""),
                 "code": code})
        return {"kept": len(kept), "dropped": len(dropped),
                "dropped_samples": dropped[:8]}

    @app.get("/api/class/options")
    def api_class_options():
        """从实际数据里汇总出现的班级标识，供用户挑选（附条数与最晚截止时间，便于辨认）。"""
        svc.state.refresh()
        cfg = settings.class_cfg
        agg: dict[str, dict] = {}
        for rec in svc.state.data.get("homeworks", {}).values():
            course = rec.get("course_name", "")
            if not classfilter.applies(course, cfg):
                continue
            code = classfilter.extract_class(rec.get("title", ""), cfg.get("separator", "-"))
            if not code:
                continue
            d = agg.setdefault(code, {"code": code, "count": 0, "latest_ddl": "",
                                      "course": course, "samples": []})
            d["count"] += 1
            if rec.get("ddl") and rec["ddl"] > d["latest_ddl"]:
                d["latest_ddl"] = rec["ddl"]
            if len(d["samples"]) < 2:
                d["samples"].append(rec.get("title", "")[:44])
        opts = sorted(agg.values(), key=lambda x: x["latest_ddl"], reverse=True)
        if not opts:
            return {"options": [], "hint": "没有识别到任何班级标识"}
        # 提醒用户：最晚的那一档才可能是当前学期的
        for o in opts:
            o["latest_ddl_display"] = o["latest_ddl"][:10] if o["latest_ddl"] else "—"
        return {"options": opts,
                "hint": "按最晚截止时间排序；当前学期的那一档通常排在最前面。"}

    @app.get("/api/settings/notify")
    def api_get_notify():
        n = settings.notify_cfg
        dg = n.get("daily_digest") or {}
        return {
            "desktop": bool((n.get("desktop") or {}).get("enabled")),
            "email": bool((n.get("email") or {}).get("enabled")),
            "wechat": bool((n.get("wechat") or {}).get("enabled")),
            "instant_24h": bool(n.get("instant_24h", True)),
            "digest_enabled": bool(dg.get("enabled", True)),
            "digest_time": str(dg.get("time") or "12:30"),
            "digest_scope": str(dg.get("scope") or "all"),
            "digest_include_overdue": bool(dg.get("include_overdue", True)),
            "last_digest_date": (svc.state.data.get("digest_sent_date") or ""),
        }

    @app.post("/api/settings/notify")
    async def api_save_notify(request: Request):
        body = await request.json()
        if body.get("csrf") != app.state.csrf:
            return JSONResponse({"ok": False, "err": "CSRF 校验失败"}, status_code=403)

        t = str(body.get("digest_time") or "12:30").strip()
        if not re.match(r"^\d{1,2}:\d{2}$", t):
            return {"ok": False, "err": "摘要时间格式应为 HH:MM，例如 12:30"}
        hh, mm = (int(x) for x in t.split(":"))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return {"ok": False, "err": "摘要时间超出范围"}

        upd = {
            "instant_24h": bool(body.get("instant_24h")),
            "daily_digest": {
                "enabled": bool(body.get("digest_enabled")),
                "time": f"{hh:02d}:{mm:02d}",
                "scope": "submittable" if body.get("digest_scope") == "submittable" else "all",
                "include_overdue": bool(body.get("digest_include_overdue")),
            },
            "desktop": {"enabled": bool(body.get("desktop"))},
            "email": {"enabled": bool(body.get("email"))},
            "wechat": {"enabled": bool(body.get("wechat"))},
        }

        path = os.path.join(settings.root, "config", "config.yaml")
        cfg = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        n = cfg.setdefault("notify", {})
        n["instant_24h"] = upd["instant_24h"]
        n["daily_digest"] = upd["daily_digest"]
        for ch in ("desktop", "email", "wechat"):
            n.setdefault(ch, {}).update(upd[ch])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        # 同步内存，立即生效
        live = settings.raw.setdefault("notify", {})
        live["instant_24h"] = upd["instant_24h"]
        live["daily_digest"] = upd["daily_digest"]
        for ch in ("desktop", "email", "wechat"):
            live.setdefault(ch, {}).update(upd[ch])
        log.info("通知设置已更新: 桌面=%s 24h即时=%s 摘要=%s@%s",
                 upd["desktop"]["enabled"], upd["instant_24h"],
                 upd["daily_digest"]["enabled"], upd["daily_digest"]["time"])
        return {"ok": True, "note": "已保存并立即生效"}

    @app.post("/api/notify/test")
    async def api_notify_test(request: Request):
        """发一条测试通知，含「弹完不影响通知留存」的行为验证。"""
        body = await request.json()
        if body.get("csrf") != app.state.csrf:
            return JSONResponse({"ok": False, "err": "CSRF 校验失败"}, status_code=403)

        def work():
            from ..notify.base import NotifyMessage
            d = disp.Dispatcher(svc.build_notifiers(), settings.notify_cfg, log)
            if body.get("kind") == "digest":
                live = svc.maybe_send_daily_digest()
                if live:
                    return {"ok": True, "detail": live["results"]}
                msg = svc.build_digest_message()
                if msg is None:
                    return {"ok": False, "err": "当前没有未提交作业，摘要为空"}
                return {"ok": True, "detail": d.send(msg)}
            msg = NotifyMessage(title="[测试] 北化作业助手通知",
                                body="这是一条测试通知。\n课程：大学物理实验(II)\n作业：《单缝衍射》实验报告\n剩 4 天 4 小时",
                                tier="d24", urgent=True,
                                url=settings.notify_cfg.get("dashboard_url"))
            return {"ok": True, "detail": d.send(msg)}

        return await asyncio.to_thread(work)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # ---------- 提交：草稿 / 预演 / 确认 ----------
    @app.post("/api/draft")
    async def api_draft(request: Request):
        """收下内容，落盘成草稿，并立刻做一次 dry-run 预演。"""
        form = await request.form()
        if form.get("csrf") != app.state.csrf:
            return JSONResponse({"ok": False, "err": "CSRF 校验失败"}, status_code=403)
        course_id = (form.get("course_id") or "").strip()
        hwtid = (form.get("hwtid") or "").strip()
        if not course_id or not hwtid:
            return {"ok": False, "err": "缺少 course_id / hwtid"}

        text = form.get("text") or ""
        name_template = (form.get("name_template") or "").strip()
        name_fields = {}
        raw_fields = form.get("name_fields") or ""
        if raw_fields:
            try:
                name_fields = json.loads(raw_fields)
            except ValueError:
                name_fields = {}
        up = form.get("file")
        file_bytes = None
        upload_name = ""
        if up is not None and getattr(up, "filename", ""):
            file_bytes = await up.read()
            upload_name = up.filename
        if not text and file_bytes is None:
            return {"ok": False, "err": "没有内容：请填文本或选一个文件"}

        def work():
            draft = app.state.submit.create_draft(
                course_id, hwtid, text=text, file_bytes=file_bytes,
                upload_name=upload_name, name_template=name_template,
                name_fields=name_fields)
            return app.state.submit.preview(draft.token)

        return await asyncio.to_thread(work)

    @app.get("/api/preview/{token}")
    def api_preview(token: str):
        return app.state.submit.preview(token)

    @app.get("/submit/preview/{token}", response_class=HTMLResponse)
    def submit_preview_page(request: Request, token: str):
        return templates.TemplateResponse(request, "preview.html", {
            "csrf": app.state.csrf, "token": token})

    @app.post("/api/submit/confirm")
    async def api_submit_confirm(request: Request):
        body = await request.json()
        if body.get("csrf") != app.state.csrf:
            return JSONResponse({"ok": False, "err": "CSRF 校验失败"}, status_code=403)
        token = body.get("token") or ""
        typed = body.get("typed") or ""
        return await asyncio.to_thread(app.state.submit.confirm, token, typed)

    @app.post("/api/submit/cancel")
    async def api_submit_cancel(request: Request):
        body = await request.json()
        if body.get("csrf") != app.state.csrf:
            return JSONResponse({"ok": False, "err": "CSRF 校验失败"}, status_code=403)
        token = body.get("token") or ""
        d = app.state.submit.get(token)
        if d:
            d.state = "CANCELLED"
            app.state.submit._save(d)
            app.state.submit.audit("cancel", {"token": token})
        return {"ok": True}

    @app.get("/api/submit/status/{token}")
    def api_submit_status(token: str):
        d = app.state.submit.get(token)
        if not d:
            return {"ok": False, "err": "无此令牌"}
        return {"ok": True, "state": d.state, "used": d.used, "result": d.result}

    return app


def _degraded(svc) -> list[str]:
    d = svc.__dict__.get("_degraded")
    return d or []


def _start_scan(svc, app) -> bool:
    if app.state.scanning:
        return False

    def work():
        app.state.scanning = True
        try:
            app.state.last_result = svc.run_once()
        except Exception as e:  # noqa: BLE001
            svc.board.publish({"kind": "scan_error", "err": str(e)})
        finally:
            app.state.scanning = False

    threading.Thread(target=work, name="scan", daemon=True).start()
    return True
