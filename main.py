from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import httpx
import asyncio
import json
import random
from datetime import datetime

app = FastAPI()

# Serve static assets (CSS/JS used by the shell/sidebar/themes)
try:
    app.mount("/statics", StaticFiles(directory="statics"), name="statics")
except Exception:
    pass

# Inject global shell (sidebar + theme system) into every HTML response.
SHELL_HEAD = (
    '<link rel="stylesheet" href="/statics/css/sennintube-shell.css">'
    '<script>(function(){try{var t=localStorage.getItem("st-theme");'
    'if(!t){t=(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches)?"dark":"light";}'
    'document.documentElement.setAttribute("data-theme",t);}catch(e){}})();</script>'
)
SHELL_BODY = '<script src="/statics/js/sennintube-shell.js" defer></script>'

@app.middleware("http")
async def inject_shell(request, call_next):
    response = await call_next(request)
    try:
        ct = response.headers.get("content-type", "")
        if "text/html" not in ct:
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="ignore")
        if "sennintube-shell.css" not in text:
            if "</head>" in text:
                text = text.replace("</head>", SHELL_HEAD + "</head>", 1)
            if "</body>" in text:
                text = text.replace("</body>", SHELL_BODY + "</body>", 1)
        new_body = text.encode("utf-8")
        headers = dict(response.headers)
        headers["content-length"] = str(len(new_body))
        return Response(content=new_body, status_code=response.status_code,
                        headers=headers, media_type=ct)
    except Exception:
        return response

templates = Jinja2Templates(directory="templates")
templates.env.add_extension('jinja2.ext.do')

INVIDIOUS_INSTANCES = [
  "https://yt.omada.cafe",
  "https://invidious.ritoge.com",
  "https://invidious.darkness.services",
  "https://invidious.f5.si",
  "https://invidious.ducks.party",
  "https://y.com.sb",
  "https://super8.absturztau.be",
  "https://inv.zoomerville.com",
  "https://invidious.nerdvpn.de",
  "https://inv.thepixora.com"
]

# Primary instance: ALWAYS try this first per user request
PRIMARY_INSTANCE = "https://yt.omada.cafe"

limits = httpx.Limits(max_connections=300, max_keepalive_connections=100)
client_session = httpx.AsyncClient(timeout=10.0, limits=limits, follow_redirects=True)

async def fetch_invidious(endpoint: str, params: dict = None, force_instance: str = None):
    if force_instance:
        instances = [force_instance] + [i for i in INVIDIOUS_INSTANCES if i != force_instance]
    else:
        # Always prefer the primary, then random fallback
        others = [i for i in INVIDIOUS_INSTANCES if i != PRIMARY_INSTANCE]
        random.shuffle(others)
        instances = [PRIMARY_INSTANCE] + others
    
    last_error = None
    for instance in instances:
        try:
            url = f"{instance.rstrip('/')}/api/v1{endpoint}"
            response = await client_session.get(url, params=params, timeout=4.5)
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.HTTPStatusError, Exception) as e:
            last_error = e
            continue
    
    raise last_error if last_error else Exception("All instances failed")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = Query(...), page: int = 1, type: str = "all", force_instance: str = Query(None)):
    try:
        async def do_fetch(params):
            if force_instance:
                return await fetch_invidious("/search", params, force_instance=force_instance)
            instances = list(INVIDIOUS_INSTANCES)
            random.shuffle(instances)
            target_instances = instances[:4]
            async def fetch_task(instance):
                url = f"{instance.rstrip('/')}/api/v1/search"
                resp = await client_session.get(url, params=params, timeout=4.0)
                resp.raise_for_status()
                return resp.json()
            tasks = [asyncio.create_task(fetch_task(inst)) for inst in target_instances]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            data = None
            for task in done:
                try:
                    data = task.result()
                    break
                except:
                    continue
            for task in pending:
                task.cancel()
            if data is None:
                data = await fetch_invidious("/search", params)
            return data

        def normalize(items, force_type=None):
            out = []
            for item in items:
                out.append({
                    "type": force_type or item.get("type"),
                    "videoId": item.get("videoId"),
                    "playlistId": item.get("playlistId"),
                    "authorId": item.get("authorId"),
                    "title": item.get("title"),
                    "lengthSeconds": item.get("lengthSeconds"),
                    "author": item.get("author"),
                    "authorThumbnails": item.get("authorThumbnails"),
                    "videoThumbnails": item.get("videoThumbnails"),
                    "viewCountText": item.get("viewCountText"),
                    "viewCount": item.get("viewCount"),
                    "publishedText": item.get("publishedText"),
                    "subCountText": item.get("subCountText"),
                    "videoCount": item.get("videoCount"),
                })
            return out

        if type == "all":
            short_task = asyncio.create_task(do_fetch({"q": f"{q} shorts", "page": page, "type": "video"}))
            channel_task = asyncio.create_task(do_fetch({"q": q, "page": page, "type": "channel"}))
            video_task = asyncio.create_task(do_fetch({"q": q, "page": page, "type": "video"}))
            shorts_data, channels_data, videos_data = [], [], []
            try: shorts_data = await short_task
            except: pass
            try: channels_data = await channel_task
            except: pass
            try: videos_data = await video_task
            except: pass
            results = (
                normalize(shorts_data, force_type="short")
                + normalize([c for c in channels_data if c.get("type") == "channel"])
                + normalize([v for v in videos_data if v.get("type") == "video"])
            )
        else:
            search_type = type if type != "short" else "video"
            query_q = q if type != "short" else f"{q} shorts"
            data = await do_fetch({"q": query_q, "page": page, "type": search_type})
            results = normalize(data, force_type="short" if type == "short" else None)

        return templates.TemplateResponse("search.html", {
            "request": request,
            "query": q,
            "results": results,
            "type": type,
            "page": page
        })
    except httpx.TimeoutException:
        return templates.TemplateResponse("apitimeout.html", {"request": request})
    except Exception:
        return templates.TemplateResponse("apiallerror.html", {"request": request, "instances": INVIDIOUS_INSTANCES})

@app.get("/shorts/{v}", response_class=HTMLResponse)
async def shorts_player(request: Request, v: str, force_instance: str = Query(None)):
    try:
        video_task = fetch_invidious(f"/videos/{v}", force_instance=force_instance)
        video_data = await video_task

        format_streams = video_data.get("formatStreams", [])
        if format_streams:
            video_urls = [fmt.get("url") for fmt in format_streams]
        else:
            adaptive = video_data.get("adaptiveFormats", [])
            video_urls = [fmt.get("url") for fmt in adaptive if "video" in fmt.get("type", "")]

        # 関連Shorts: 推奨動画から短尺 (<=60s) のみ厳密抽出
        related = []
        for rec in (video_data.get("recommendedVideos") or []):
            length = rec.get("lengthSeconds") or 0
            if 0 < length <= 60 and rec.get("videoId"):
                related.append({
                    "videoId": rec.get("videoId"),
                    "title": rec.get("title"),
                    "author": rec.get("author"),
                    "viewCountText": rec.get("viewCountText"),
                })
            if len(related) >= 8:
                break

        # 足りない場合は Shorts 検索で補完
        if len(related) < 6:
            try:
                extra = await _fetch_shorts_list(video_data.get("title", "") or "shorts", 1)
                seen = {r["videoId"] for r in related} | {v}
                for it in extra:
                    if it["videoId"] in seen:
                        continue
                    related.append({
                        "videoId": it["videoId"],
                        "title": it["title"],
                        "author": it["author"],
                        "viewCountText": it.get("viewCountText"),
                    })
                    seen.add(it["videoId"])
                    if len(related) >= 12:
                        break
            except Exception:
                pass

        return templates.TemplateResponse("short.html", {
            "request": request,
            "videoid": v,
            "video_title": video_data.get("title"),
            "videourls": video_urls,
            "author": video_data.get("author"),
            "author_id": video_data.get("authorId"),
            "view_count": video_data.get("viewCount", 0),
            "like_count": video_data.get("likeCount", 0),
            "description": video_data.get("descriptionHtml", "").replace("\n", "<br>"),
            "related_shorts": related,
        })
    except httpx.TimeoutException:
        return templates.TemplateResponse("apitimeout.html", {"request": request})
    except Exception:
        return templates.TemplateResponse("apiallerror.html", {"request": request, "instances": INVIDIOUS_INSTANCES})

@app.get("/api/shorts_meta/{v}")
async def shorts_meta(v: str):
    try:
        video_data = await fetch_invidious(f"/videos/{v}")
        fs = video_data.get("formatStreams", [])
        if fs:
            urls = [f.get("url") for f in fs]
        else:
            urls = [f.get("url") for f in video_data.get("adaptiveFormats", []) if "video" in f.get("type", "")]
        return {
            "videoId": v,
            "url": urls[0] if urls else None,
            "title": video_data.get("title"),
            "author": video_data.get("author"),
            "viewCount": video_data.get("viewCount", 0),
            "likeCount": video_data.get("likeCount", 0),
            "description": (video_data.get("descriptionHtml") or "").replace("\n", "<br>"),
        }
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=500)


# ---- Shorts feed: strict shorts-only with batch metadata ----
async def _fetch_shorts_list(q: str, page: int = 1):
    """Fetch shorts-only candidates from primary instance, racing fallbacks."""
    params = {"q": f"{q} #shorts", "page": page, "type": "video", "sort_by": "relevance"}
    instances = [PRIMARY_INSTANCE] + [i for i in INVIDIOUS_INSTANCES if i != PRIMARY_INSTANCE][:3]

    async def t(inst):
        url = f"{inst.rstrip('/')}/api/v1/search"
        r = await client_session.get(url, params=params, timeout=4.0)
        r.raise_for_status()
        return r.json()

    tasks = [asyncio.create_task(t(i)) for i in instances]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    data = None
    for d in done:
        try:
            data = d.result()
            break
        except:
            continue
    for p in pending:
        p.cancel()
    if data is None:
        data = []
    # Strict short filter: <= 60s, has videoId, type video
    out = []
    for it in (data or []):
        if it.get("type") != "video":
            continue
        ln = it.get("lengthSeconds") or 0
        if 0 < ln <= 60 and it.get("videoId"):
            out.append({
                "videoId": it.get("videoId"),
                "title": it.get("title"),
                "author": it.get("author"),
                "authorId": it.get("authorId"),
                "lengthSeconds": ln,
                "viewCount": it.get("viewCount", 0),
                "viewCountText": it.get("viewCountText"),
            })
    return out


@app.get("/api/shorts_feed")
async def shorts_feed(q: str = "shorts", page: int = 1):
    """Return a list of strictly-short videos for the Shorts feed."""
    try:
        # Fetch two pages in parallel for a larger pool
        results = await asyncio.gather(
            _fetch_shorts_list(q, page),
            _fetch_shorts_list(q, page + 1),
            return_exceptions=True,
        )
        items = []
        seen = set()
        for r in results:
            if isinstance(r, Exception):
                continue
            for it in r:
                if it["videoId"] in seen:
                    continue
                seen.add(it["videoId"])
                items.append(it)
        return {"items": items}
    except Exception as e:
        return Response(content=json.dumps({"items": [], "error": str(e)}),
                        media_type="application/json", status_code=200)


@app.get("/api/shorts_batch")
async def shorts_batch(ids: str):
    """Resolve multiple short video stream URLs concurrently. ids = comma-separated."""
    vids = [v.strip() for v in ids.split(",") if v.strip()][:24]

    # Fastest path: hit yt.omada.cafe (PRIMARY) directly for every id with a
    # tight timeout. Only fall back to other instances if PRIMARY fails for
    # that specific id. Racing all instances per-id added latency and load,
    # so we trust the primary and parallelize across ids instead.
    backup_pool = [i for i in INVIDIOUS_INSTANCES if i != PRIMARY_INSTANCE]

    async def fetch_at(inst, v, timeout):
        url = f"{inst.rstrip('/')}/api/v1/videos/{v}"
        r = await client_session.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def one(v):
        d = None
        # 1) Primary: yt.omada.cafe, tight 1.8s timeout
        try:
            d = await fetch_at(PRIMARY_INSTANCE, v, 1.8)
        except Exception:
            d = None
        # 2) Fallback: race the next 3 backups, take first success (1.8s cap)
        if d is None and backup_pool:
            picks = backup_pool[:3]
            tasks = [asyncio.create_task(fetch_at(i, v, 1.8)) for i in picks]
            try:
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED, timeout=2.0)
                for t in done:
                    try:
                        d = t.result(); break
                    except Exception:
                        continue
                for t in pending:
                    t.cancel()
            except Exception:
                pass
        if d is None:
            return None
        try:
            ln = d.get("lengthSeconds") or 0
            if ln > 90:  # not a short
                return None
            fs = d.get("formatStreams", [])
            if fs:
                url = fs[0].get("url")
            else:
                adap = [f for f in d.get("adaptiveFormats", []) if "video" in f.get("type", "")]
                url = adap[0].get("url") if adap else None
            return {
                "videoId": v,
                "url": url,
                "title": d.get("title"),
                "author": d.get("author"),
                "authorId": d.get("authorId"),
                "viewCount": d.get("viewCount", 0),
                "likeCount": d.get("likeCount", 0),
                "lengthSeconds": ln,
            }
        except Exception:
            return None

    results = await asyncio.gather(*(one(v) for v in vids))
    return {"items": [r for r in results if r]}


@app.get("/tools", response_class=HTMLResponse)
async def read_tools(request: Request):
    return templates.TemplateResponse("tools.html", {"request": request})


@app.get("/watch", response_class=HTMLResponse)
async def watch(request: Request, v: str = Query(...), force_instance: str = Query(None)):
    try:
        async def fetch_video_speculative(vid):
            if force_instance:
                return await fetch_invidious(f"/videos/{vid}", force_instance=force_instance)
            
            instances = list(INVIDIOUS_INSTANCES)
            random.shuffle(instances)
            target_instances = instances[:4]
            
            async def task(instance):
                url = f"{instance.rstrip('/')}/api/v1/videos/{vid}"
                resp = await client_session.get(url, timeout=4.0)
                resp.raise_for_status()
                return resp.json()

            tasks = [asyncio.create_task(task(inst)) for inst in target_instances]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            
            res = None
            for t in done:
                try: res = t.result(); break
                except: continue
            
            for t in pending: t.cancel()
            
            if res is None: res = await fetch_invidious(f"/videos/{vid}")
            return res

        video_task = fetch_video_speculative(v)
        comment_task = fetch_invidious(f"/comments/{v}", force_instance=force_instance)
        video_data, comment_data = await asyncio.gather(video_task, comment_task, return_exceptions=True)

        if isinstance(video_data, Exception): raise video_data
        
        adaptive = video_data.get("adaptiveFormats", [])
        
        audio_url = None
        for f in adaptive:
            if "audio" in f.get("type", ""):
                if f.get("language") == "ja":
                    audio_url = f.get("url")
                    break

        # Fallbacks: prefer webm/opus audio, then any audio
        if not audio_url:
            for f in adaptive:
                t = f.get("type", "")
                if "audio" in t and "webm" in (f.get("container") or ""):
                    audio_url = f.get("url"); break
        if not audio_url:
            for f in adaptive:
                if "audio" in f.get("type", ""):
                    audio_url = f.get("url"); break

        # m4a (mp4 audio) for pairing with mp4 video-only high-quality streams.
        # Prefer Japanese track if present, then highest bitrate m4a.
        m4a_audio_url = None
        m4a_candidates = [
            f for f in adaptive
            if "audio" in f.get("type", "")
            and (("mp4" in (f.get("container") or "")) or ("mp4" in f.get("type", "")))
        ]
        for f in m4a_candidates:
            if f.get("language") == "ja":
                m4a_audio_url = f.get("url"); break
        if not m4a_audio_url and m4a_candidates:
            try:
                m4a_candidates.sort(key=lambda x: int(x.get("bitrate") or 0), reverse=True)
            except Exception:
                pass
            m4a_audio_url = m4a_candidates[0].get("url")

        format_streams = video_data.get("formatStreams", [])
        
        stream_urls = [{
            "url": fmt.get("url"),
            "resolution": fmt.get("qualityLabel"),
            "format": "mp4/mixed",
            "audioUrl": ""
        } for fmt in format_streams]
        
        stream_urls.extend({
            "url": fmt.get("url"),
            "resolution": fmt.get("qualityLabel"),
            "format": "webm/videoOnly",
            "audioUrl": audio_url
        } for fmt in adaptive if "video" in fmt.get("type", "") and "webm" in fmt.get("container", ""))

        # High-quality mp4 video-only paired with m4a audio (better Safari/iOS support
        # and gives access to 1080p+ tracks that formatStreams doesn't include).
        stream_urls.extend({
            "url": fmt.get("url"),
            "resolution": fmt.get("qualityLabel"),
            "format": "mp4/videoOnly",
            "audioUrl": m4a_audio_url or audio_url,
        } for fmt in adaptive if "video" in fmt.get("type", "") and "mp4" in (fmt.get("container") or ""))

        video_urls = [fmt.get("url") for fmt in format_streams] or \
                     [fmt.get("url") for fmt in adaptive if "video" in fmt.get("type", "")]

        recommended = [{
            "video_id": rec.get("videoId"),
            "title": rec.get("title"),
            "author": rec.get("author"),
            "view_count_text": rec.get("viewCountText")
        } for rec in video_data.get("recommendedVideos", [])]

        author_thumbs = video_data.get("authorThumbnails", [])
        author_icon = author_thumbs[-1]["url"] if author_thumbs else ""

        youtube_url = f"https://www.youtube.com/watch?v={v}"

        response = templates.TemplateResponse("watch.html", {
            "request": request,
            "videoid": v,
            "video_title": video_data.get("title"),
            "videourls": video_urls,
            "streamUrls": stream_urls,
            "author": video_data.get("author"),
            "author_id": video_data.get("authorId"),
            "author_icon": author_icon,
            "subscribers_count": video_data.get("subCountText", "非公開"),
            "view_count": video_data.get("viewCount", 0),
            "like_count": video_data.get("likeCount", 0),
            "description": video_data.get("descriptionHtml", "").replace("\n", "<br>"),
            "recommended_videos": recommended,
            "comments": comment_data.get("comments", []) if not isinstance(comment_data, Exception) else [],
            "youtube_url": youtube_url
        })

        try:
            history_json = request.cookies.get("history", "[]")
            history = json.loads(history_json)
            history = [item for item in history if item.get("videoId") != v]
            history.append({
                "videoId": v,
                "title": video_data.get("title"),
                "author": video_data.get("author"),
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            if len(history) > 50: history = history[-50:]
            response.set_cookie(key="history", value=json.dumps(history), max_age=2592000, httponly=True)
        except:
            pass

        return response

    except httpx.TimeoutException:
        return templates.TemplateResponse("apitimeout.html", {"request": request})
    except Exception:
        return templates.TemplateResponse("apiallerror.html", {"request": request, "instances": INVIDIOUS_INSTANCES})

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    try:
        history_list = json.loads(request.cookies.get("history", "[]"))
    except:
        history_list = []
    history_list.reverse()
    return templates.TemplateResponse("history.html", {"request": request, "history": history_list})

@app.get("/history/clear")
async def clear_history():
    response = RedirectResponse(url="/history")
    response.delete_cookie("history")
    return response

@app.get("/playlist", response_class=HTMLResponse)
async def playlist(request: Request, list: str = Query(...), force_instance: str = Query(None)):
    try:
        data = await fetch_invidious(f"/playlists/{list}", force_instance=force_instance)
        return templates.TemplateResponse("playlist.html", {
            "request": request,
            "title": data.get("title"),
            "playlistId": list,
            "author": data.get("author"),
            "authorId": data.get("authorId"),
            "videos": data.get("videos", []),
            "description": data.get("descriptionHtml", "")
        })
    except httpx.TimeoutException:
        return templates.TemplateResponse("apitimeout.html", {"request": request})
    except Exception:
        return templates.TemplateResponse("apiallerror.html", {"request": request, "instances": INVIDIOUS_INSTANCES})

@app.get("/channel/{ucid}", response_class=HTMLResponse)
async def channel(request: Request, ucid: str, sort_by: str = "newest", tab: str = "home", force_instance: str = Query(None)):
    try:
        tasks = [
            fetch_invidious(f"/channels/{ucid}", force_instance=force_instance),
            fetch_invidious(f"/channels/{ucid}/videos", {"sort_by": sort_by}, force_instance=force_instance),
            fetch_invidious(f"/channels/{ucid}/shorts", force_instance=force_instance),
            fetch_invidious(f"/channels/{ucid}/playlists", force_instance=force_instance),
            fetch_invidious(f"/channels/{ucid}/community", force_instance=force_instance)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        channel_data = results[0] if not isinstance(results[0], Exception) else {}
        videos_data = results[1] if not isinstance(results[1], Exception) else {}
        shorts_data = results[2] if not isinstance(results[2], Exception) else {}
        playlists_data = results[3] if not isinstance(results[3], Exception) else {}
        community_data = results[4] if not isinstance(results[4], Exception) else {}

        # 配列（list型）のレスポンスと辞書（dict型）のレスポンスの双方に対応
        if isinstance(videos_data, list):
            final_videos = videos_data
        elif isinstance(videos_data, dict):
            final_videos = videos_data.get("videos", [])
        else:
            final_videos = []

        if isinstance(shorts_data, list):
            final_shorts = shorts_data
        elif isinstance(shorts_data, dict):
            final_shorts = shorts_data.get("videos", [])
        else:
            final_shorts = []

        playlists = []
        for pl in playlists_data.get("playlists", []) if isinstance(playlists_data, dict) else (playlists_data if isinstance(playlists_data, list) else []):
            thumb = pl.get("playlistThumbnail", "")
            if thumb and not thumb.startswith("http"):
                thumb = f"https://img.youtube.com/vi/{thumb}/mqdefault.jpg"
            playlists.append({
                "id": pl.get("playlistId", ""),
                "title": pl.get("title", ""),
                "video_count": pl.get("videoCount", 0),
                "thumbnail": thumb,
            })

        author_name = channel_data.get("author")
        author_icon = channel_data.get("authorThumbnails", [{"url": ""}])[-1]["url"] if channel_data.get("authorThumbnails") else ""

        # バナー画像 (最高解像度を選ぶ)
        banner_url = ""
        banners = channel_data.get("authorBanners") or []
        if isinstance(banners, list) and banners:
            try:
                banner_url = sorted(banners, key=lambda b: b.get("width", 0))[-1].get("url", "")
            except Exception:
                banner_url = banners[-1].get("url", "")

        # 一番人気の動画 (再生回数最大)
        popular_video = None
        try:
            sortable = [v for v in final_videos if isinstance(v, dict) and v.get("videoId")]
            if sortable:
                popular_video = max(sortable, key=lambda v: int(v.get("viewCount") or 0))
        except Exception:
            popular_video = final_videos[0] if final_videos else None

        # yt.omada.cafe (PRIMARY) から人気動画のストリームURL/説明文を取得しプレビューに使う
        if popular_video and popular_video.get("videoId"):
            try:
                pv_data = await fetch_invidious(
                    f"/videos/{popular_video['videoId']}",
                    force_instance=PRIMARY_INSTANCE,
                )
                if isinstance(pv_data, dict):
                    fmt_streams = pv_data.get("formatStreams") or []
                    # 720p/360p等のmuxedストリームから一番高解像度を選ぶ
                    def _res_key(f):
                        try:
                            return int((f.get("qualityLabel") or "0p").rstrip("p"))
                        except Exception:
                            return 0
                    fmt_streams_sorted = sorted(fmt_streams, key=_res_key, reverse=True)
                    if fmt_streams_sorted:
                        popular_video["stream_url"] = fmt_streams_sorted[0].get("url")
                    popular_video["description"] = pv_data.get("description") or pv_data.get("descriptionHtml") or ""
                    if not popular_video.get("viewCountText"):
                        vc = pv_data.get("viewCount")
                        if vc:
                            popular_video["viewCountText"] = f"{int(vc):,} views"
            except Exception:
                pass

        comments_list = community_data.get("comments", []) if isinstance(community_data, dict) else (community_data if isinstance(community_data, list) else [])
        community = [{
            "id": post.get("commentId", ""),
            "content": post.get("contentHtml", "").replace("\n", "<br>"),
            "published_text": post.get("publishedText", ""),
            "likes": post.get("likeCount", 0),
            "author": author_name,
            "author_icon": author_icon,
        } for post in comments_list]

        return templates.TemplateResponse("channel.html", {
            "request": request,
            "ucid": ucid,
            "author": author_name,
            "author_icon": author_icon,
            "banner": banner_url,
            "popular_video": popular_video,
            "sub_count": channel_data.get("subCountText", "非公開"),
            "description": channel_data.get("descriptionHtml", ""),
            "videos": final_videos,
            "shorts": final_shorts,
            "playlists": playlists,
            "community": community,
            "sort_by": sort_by,
            "tab": tab
        })
    except httpx.TimeoutException:
        return templates.TemplateResponse("apitimeout.html", {"request": request})
    except Exception:
        return templates.TemplateResponse("apiallerror.html", {"request": request, "instances": INVIDIOUS_INSTANCES})

@app.get("/suggest")
async def suggest(keyword: str):
    instances = list(INVIDIOUS_INSTANCES)
    random.shuffle(instances)
    for instance in instances:
        try:
            resp = await client_session.get(f"{instance.rstrip('/')}/api/v1/search/suggestions", params={"q": keyword}, timeout=1.5)
            if resp.status_code == 200:
                return resp.json().get("suggestions", [])
        except: continue
    return []

@app.get("/proxy/thumb")
async def proxy_thumb(v: str):
    thumb_url = f"https://i.ytimg.com/vi/{v}/mqdefault.jpg"
    try:
        resp = await client_session.get(thumb_url, timeout=4.0)
        return Response(content=resp.content, media_type="image/jpeg")
    except: return Response(status_code=404)

@app.get("/thumbnail")
async def thumbnail(v: str):
    return await proxy_thumb(v)

@app.get("/games", response_class=HTMLResponse)
async def read_games(request: Request):
    return templates.TemplateResponse("games.html", {"request": request})

@app.get("/block.html", response_class=HTMLResponse)
async def read_block(request: Request):
    return templates.TemplateResponse("block.html", {"request": request})

@app.get("/tumu.html", response_class=HTMLResponse)
async def read_tumu(request: Request):
    return templates.TemplateResponse("tumu.html", {"request": request})

@app.get("/2048.html", response_class=HTMLResponse)
async def read_2048(request: Request):
    return templates.TemplateResponse("2048.html", {"request": request})

@app.get("/status", response_class=HTMLResponse)
async def read_status(request: Request):
    async def check_instance(instance):
        start_time = asyncio.get_event_loop().time()
        try:
            resp = await client_session.get(f"{instance.rstrip('/')}/api/v1/stats", timeout=4.0)
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "instance": instance,
                    "status": "Online",
                    "latency": f"{int(latency)}ms",
                    "version": data.get("software", {}).get("version", "unknown"),
                    "users": data.get("usage", {}).get("users", {}).get("total", 0)
                }
            return {"instance": instance, "status": f"Error {resp.status_code}", "latency": "-", "version": "-", "users": "-"}
        except:
            return {"instance": instance, "status": "Offline", "latency": "-", "version": "-", "users": "-"}

    status_results = await asyncio.gather(*(check_instance(inst) for inst in INVIDIOUS_INSTANCES))
    return templates.TemplateResponse("status.html", {"request": request, "instances": status_results})

@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(request: Request):
    return templates.TemplateResponse("subscriptions.html", {"request": request})

@app.get("/bbs", response_class=HTMLResponse)
async def bbs_page(request: Request):
    return templates.TemplateResponse("bbs.html", {"request": request})

@app.get("/ytdl", response_class=HTMLResponse)
async def ytdl_page(request: Request):
    return templates.TemplateResponse("bbs.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
