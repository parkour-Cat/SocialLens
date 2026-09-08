"""Download pipeline (docs/design.md §9).

A download is a Task with action "download". The pipeline: fetch the post through the extension
(get_post), ask the adapter for download sources (direct media URLs, or platform-resolved streams
such as B 站 playurl / YouTube streamingData), then stream each file with httpx into
data/downloads/{platform}/{author_id}/{post_id}_{index}.{ext}. Progress lives in task.result while
running; the final result lists the files.

Sources are plain dicts:
  {"index": int, "type": "video"|"image"|"audio", "url": str, "headers": {..}, "ext": "mp4",
   "parts": [{"url", "headers"}, ...]   # optional: several streams merged with ffmpeg (B 站 DASH)
   "tool": "yt-dlp"}                    # optional: hand the URL to an external tool
"""

from __future__ import annotations

import asyncio
import mimetypes
import re
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from ..logging_setup import get_logger
from ..models.errors import ErrorCode, SocialLensError
from ..models.task import Task, TaskStatus
from ..platforms.registry import PlatformRegistry
from ..tasks.manager import TaskManager

log = get_logger("download")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
CHUNK = 256 * 1024
PROGRESS_EVERY_S = 1.0
EXT_BY_TYPE = {"video": "mp4", "image": "jpg", "audio": "m4a"}

ClientFactory = Callable[[], httpx.AsyncClient]


def system_proxy() -> str | None:
    """The proxy the user's browser most likely uses: env HTTPS_PROXY/HTTP_PROXY, else the OS
    setting (Windows registry / macOS `scutil --proxy`). None when there is none."""
    import os

    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        if os.environ.get(key):
            return os.environ[key]
    try:
        import winreg  # Windows only

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            if not winreg.QueryValueEx(k, "ProxyEnable")[0]:
                return None
            server = str(winreg.QueryValueEx(k, "ProxyServer")[0] or "")
        if "=" in server:  # per-protocol "http=host:port;https=host:port"
            parts = dict(item.split("=", 1) for item in server.split(";") if "=" in item)
            server = parts.get("https") or parts.get("http") or ""
        if not server:
            return None
        return server if "://" in server else f"http://{server}"
    except ImportError:
        pass
    except OSError:
        return None
    try:  # macOS
        import subprocess

        out = subprocess.run(["scutil", "--proxy"], capture_output=True, text=True, timeout=3).stdout
        cfg = dict(line.strip().split(" : ", 1) for line in out.splitlines() if " : " in line)
        if cfg.get("HTTPSEnable") == "1" and cfg.get("HTTPSProxy"):
            return f"http://{cfg['HTTPSProxy']}:{cfg.get('HTTPSPort', '80')}"
        if cfg.get("HTTPEnable") == "1" and cfg.get("HTTPProxy"):
            return f"http://{cfg['HTTPProxy']}:{cfg.get('HTTPPort', '80')}"
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def resolve_proxy(setting: str | None) -> str | None:
    if not setting or setting.lower() == "off":
        return None
    if setting.lower() == "system":
        return system_proxy()
    return setting


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ytdlp_path() -> str | None:
    return shutil.which("yt-dlp")


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name)).strip("._") or "unknown"


def _ext_from(url: str, content_type: str | None, fallback: str) -> str:
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        known = {"video/mp4": "mp4", "video/webm": "webm", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "audio/mp4": "m4a", "video/x-flv": "flv"}
        if ct in known:
            return known[ct]
        guessed = mimetypes.guess_extension(ct)
        if guessed and ct.split("/")[0] in ("video", "image", "audio"):
            return guessed.lstrip(".")
    m = re.search(r"\.([a-z0-9]{2,4})(?:$|\?)", urlparse(url).path.lower() + "?")
    if m and m.group(1) in ("mp4", "webm", "jpg", "jpeg", "png", "webp", "gif", "m4a", "mp3", "flv", "m4s"):
        return "jpg" if m.group(1) == "jpeg" else m.group(1)
    return fallback


class DownloadManager:
    def __init__(self, root: Path, registry: PlatformRegistry, tasks: TaskManager, client_factory: ClientFactory | None = None, proxy: str | None = "system") -> None:
        self.root = root
        self.registry = registry
        self.tasks = tasks
        self.proxy = resolve_proxy(proxy)
        if self.proxy:
            log.info("downloads use proxy", proxy=self.proxy)
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0), proxy=self.proxy))
        self._running: dict[str, asyncio.Task] = {}

    # ---- public --------------------------------------------------------------------

    async def start(self, platform: str, post_id: str, params: dict[str, Any]) -> Task:
        adapter = self.registry.get(platform)
        if adapter is None:
            raise SocialLensError(ErrorCode.UNKNOWN_PLATFORM, f"unknown platform: {platform}")
        if adapter.capability("get_post") is None:
            raise SocialLensError(ErrorCode.UNSUPPORTED, f"{platform} has no get_post, nothing to download")
        task = Task(platform=platform, action="download", params={"post_id": post_id, **params}, strategy="backend", timeout_ms=int(params.get("timeout_s", 1800)) * 1000)
        task.result = {"post_id": post_id, "stage": "queued", "files": []}
        self.tasks.register(task, cancel=lambda: self._cancel(task.id))
        self._running[task.id] = asyncio.create_task(self._run(task))
        return task

    async def wait(self, task: Task, timeout_s: float) -> Task:
        await self.tasks.wait(task.id, timeout_s)
        return task

    def list(self, platform: str | None, limit: int) -> list[Task]:
        return [t for t in self.tasks.list(platform, None, 500) if t.action == "download"][:limit]

    # ---- pipeline ------------------------------------------------------------------

    async def _cancel(self, task_id: str) -> None:
        t = self._running.get(task_id)
        if t and not t.done():
            t.cancel()

    async def _run(self, task: Task) -> None:
        platform = task.platform
        post_id = str(task.params["post_id"])
        adapter = self.registry.get(platform)
        progress = task.result
        try:
            task.status = TaskStatus.RUNNING
            progress["stage"] = "fetching post"
            self.tasks.save(task)

            async def run(action: str, params: dict[str, Any], parse: bool = True) -> Any:
                return (await self.tasks.run(platform, action, params, parse=parse)).result

            post = await run("get_post", {"id": post_id, **{k: v for k, v in task.params.items() if k in ("xsec_token", "allow_anonymous")}})
            if not isinstance(post, dict):
                raise SocialLensError(ErrorCode.PARSE_ERROR, "get_post did not return a post")
            progress["stage"] = "resolving media"
            progress["title"] = post.get("title") or (post.get("content") or "")[:60]
            self.tasks.save(task)
            sources = await adapter.download_sources(post, run, task.params)
            index = task.params.get("media_index")
            if index is not None:
                sources = [s for s in sources if s.get("index") == int(index)]
                if not sources:
                    raise SocialLensError(ErrorCode.NOT_FOUND, f"media_index {index} not in post (has {[s.get('index') for s in await adapter.download_sources(post, run, task.params)]})")
            if not sources:
                raise SocialLensError(ErrorCode.UNSUPPORTED, f"{platform} post {post_id} has no downloadable media")

            author = (post.get("author") or {}).get("id") or "unknown"
            out_dir = self.root / platform / _safe(author)
            out_dir.mkdir(parents=True, exist_ok=True)
            progress["dir"] = str(out_dir)
            files: list[dict[str, Any]] = []
            progress["files"] = files
            for src in sources:
                entry = {"index": src.get("index"), "type": src.get("type"), "url": src.get("url"), "path": None, "bytes_done": 0, "bytes_total": None, "status": "queued"}
                files.append(entry)
            progress["stage"] = "downloading"
            self.tasks.save(task)
            for src, entry in zip(sources, files):
                stem = f"{_safe(post_id)}_{src.get('index', 0)}"
                entry["status"] = "downloading"
                try:
                    if src.get("tool") == "yt-dlp":
                        path = await self._ytdlp(src, out_dir, stem, entry, task)
                    elif src.get("parts"):
                        path = await self._merge_parts(src, out_dir, stem, entry, task)
                    else:
                        path = await self._fetch(src, out_dir / f"{stem}.{src.get('ext') or EXT_BY_TYPE.get(str(src.get('type')), 'bin')}", entry, task)
                    entry["path"] = str(path)
                    entry["status"] = "done"
                except asyncio.CancelledError:
                    raise
                except SocialLensError as e:
                    entry["status"] = "failed"
                    entry["error"] = e.to_dict()
                except Exception as e:  # noqa: BLE001
                    entry["status"] = "failed"
                    entry["error"] = {"code": "download_error", "message": repr(e)}
                self.tasks.save(task)
            failed = [f for f in files if f["status"] != "done"]
            progress["stage"] = "done" if not failed else "partial"
            if failed and len(failed) == len(files):
                first = failed[0].get("error") or {}
                self.tasks.finish(task, TaskStatus.FAILED, result=progress, error={"code": first.get("code", "download_error"), "message": f"all {len(files)} files failed: {first.get('message')}"})
            else:
                self.tasks.finish(task, TaskStatus.DONE, result=progress)
            log.info("download finished", task_id=task.id, platform=platform, post_id=post_id, files=len(files), failed=len(failed))
        except asyncio.CancelledError:
            progress["stage"] = "cancelled"
            self.tasks.finish(task, TaskStatus.CANCELLED, result=progress, error={"code": "cancelled", "message": "cancelled by client"})
        except SocialLensError as e:
            progress["stage"] = "failed"
            self.tasks.finish(task, TaskStatus.FAILED, result=progress, error=e.to_dict())
            log.warning("download failed", task_id=task.id, code=e.raw_code, message=e.message)
        except Exception as e:  # noqa: BLE001
            progress["stage"] = "failed"
            self.tasks.finish(task, TaskStatus.FAILED, result=progress, error={"code": ErrorCode.INTERNAL, "message": repr(e)})
            log.error("download crashed", task_id=task.id, error=repr(e))
        finally:
            self._running.pop(task.id, None)

    # ---- fetchers ------------------------------------------------------------------

    async def _fetch(self, src: dict[str, Any], target: Path, entry: dict[str, Any], task: Task) -> Path:
        urls = [src["url"], *(src.get("backup_urls") or [])]
        headers = {"User-Agent": UA, **(src.get("headers") or {})}
        last: Exception | None = None
        for url in urls:
            try:
                return await self._stream(url, headers, target, entry, task)
            except (httpx.HTTPError, SocialLensError) as e:
                last = e
                log.warning("download source failed", url=url[:120], error=repr(e))
        raise SocialLensError(ErrorCode.INTERNAL, f"download failed: {last!r}")

    async def _stream(self, url: str, headers: dict[str, str], target: Path, entry: dict[str, Any], task: Task) -> Path:
        tmp = target.with_suffix(target.suffix + ".part")
        async with self.client_factory() as client:
            async with client.stream("GET", url, headers=headers) as res:
                if res.status_code >= 400:
                    raise SocialLensError(ErrorCode.INTERNAL, f"HTTP {res.status_code} from {urlparse(url).netloc}")
                ext = _ext_from(str(res.url), res.headers.get("content-type"), target.suffix.lstrip("."))
                final = target.with_suffix("." + ext)
                tmp = final.with_suffix(final.suffix + ".part")
                total = res.headers.get("content-length")
                entry["bytes_total"] = int(total) if total and total.isdigit() else None
                entry["bytes_done"] = 0
                last_save = time.monotonic()
                with open(tmp, "wb") as fh:
                    async for chunk in res.aiter_bytes(CHUNK):
                        fh.write(chunk)
                        entry["bytes_done"] += len(chunk)
                        if time.monotonic() - last_save > PROGRESS_EVERY_S:
                            self.tasks.save(task)
                            last_save = time.monotonic()
        tmp.replace(final)
        return final

    async def _merge_parts(self, src: dict[str, Any], out_dir: Path, stem: str, entry: dict[str, Any], task: Task) -> Path:
        ffmpeg = ffmpeg_path()
        if not ffmpeg:
            raise SocialLensError(ErrorCode.UNSUPPORTED, "merging separate video/audio streams needs ffmpeg on PATH")
        parts: list[Path] = []
        for i, part in enumerate(src["parts"]):
            sub = {"index": i, "bytes_done": 0, "bytes_total": None}
            try:
                path = await self._fetch({**part, "backup_urls": part.get("backup_urls")}, out_dir / f"{stem}.part{i}.{part.get('ext', 'm4s')}", sub, task)
            except SocialLensError:
                if part.get("optional"):  # e.g. a Reddit audio track that does not exist for silent videos
                    log.info("optional stream skipped", url=str(part.get("url"))[:100])
                    continue
                raise
            entry["bytes_done"] += sub["bytes_done"]
            parts.append(path)
        final = out_dir / f"{stem}.{src.get('ext') or 'mp4'}"
        if len(parts) == 1:  # nothing to merge
            parts[0].replace(final)
            entry["bytes_total"] = final.stat().st_size
            return final
        args = [ffmpeg, "-y", "-loglevel", "error"]
        for p in parts:
            args += ["-i", str(p)]
        args += ["-c", "copy", str(final)]
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        for p in parts:
            p.unlink(missing_ok=True)
        if proc.returncode != 0:
            raise SocialLensError(ErrorCode.INTERNAL, f"ffmpeg merge failed: {err.decode(errors='replace')[:300]}")
        entry["bytes_total"] = final.stat().st_size
        return final

    async def _ytdlp(self, src: dict[str, Any], out_dir: Path, stem: str, entry: dict[str, Any], task: Task) -> Path:
        tool = ytdlp_path()
        if not tool:
            raise SocialLensError(ErrorCode.UNSUPPORTED, "yt-dlp is not on PATH")
        template = str(out_dir / f"{stem}.%(ext)s")
        args = [tool, "--no-playlist", "-f", src.get("format") or "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b", "--merge-output-format", "mp4", "-o", template, "--no-progress"]
        if self.proxy:
            args += ["--proxy", self.proxy]
        args.append(src["url"])
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise SocialLensError(ErrorCode.INTERNAL, f"yt-dlp failed: {err.decode(errors='replace')[-300:]}")
        found = sorted(out_dir.glob(f"{stem}.*"), key=lambda p: p.stat().st_mtime)
        if not found:
            raise SocialLensError(ErrorCode.INTERNAL, "yt-dlp reported success but wrote no file")
        entry["bytes_done"] = entry["bytes_total"] = found[-1].stat().st_size
        return found[-1]
