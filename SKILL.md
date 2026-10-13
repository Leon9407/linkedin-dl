---
name: linkedin-dl
description: >-
  Download videos from LinkedIn posts (and other sites that need browser login).
  Use this whenever the user shares a LinkedIn post/feed/activity URL and wants
  to download, save, or grab the video from it — even if they just paste a
  linkedin.com link and say "下载这个视频" / "帮我把视频存下来" / "download this".
  LinkedIn blocks anonymous access (HTTP 451) and serves video only as signed
  HLS, so plain yt-dlp fails; this skill handles the login/cookie and signed-URL
  extraction that make the download work. For public YouTube/Vimeo/Twitter links
  that need no login, prefer plain yt-dlp instead.
---

# LinkedIn Video Download

Download the video from a LinkedIn post. The hard part isn't the download — it's
that LinkedIn requires an authenticated session and serves video only as signed,
expiring HLS streams. This skill carries the two pieces of state that make it work:
a logged-in cookie jar, and the full signed playlist URL.

## Why plain yt-dlp fails here

- An anonymous request to a LinkedIn post returns **HTTP 451** (Unavailable For Legal Reasons). You need login cookies.
- You **cannot** read the main Edge/Chrome profile's cookie database while the browser is running — it holds an exclusive OS-level lock. Decrypting it via DPAPI is fragile and security-sensitive.
- LinkedIn posts expose **no progressive MP4**, only HLS. The master playlist URL is signed in its query string (`e=<expiry>&v=beta&t=<token>`); drop any parameter and the CDN returns **403**.
- The CDN (`dms.licdn.com`) also rejects requests without a `linkedin.com` **Referer**.

The bundled scripts solve each of these. Don't re-derive them by hand.

## Prerequisites

- `yt-dlp` (`python -m pip install -U yt-dlp`) and `ffmpeg` on PATH (for muxing HLS).
- `playwright` with Chromium driver (`pip install playwright`) — only needed for the one-time cookie export.
- Microsoft Edge installed (per this user's global rule, always use Edge, never Chrome/Chromium).

## Workflow

### Step 1 — Make sure cookies exist and are fresh

Cookies live at `<skill>/linkedin_cookies.txt` by default. If that file is missing,
or a download later fails with 451/401/403 (session expired), run the exporter:

```bash
python scripts/export_cookies.py
```

This opens a **separate** Edge window with its own persistent profile (it coexists
with whatever Edge the user already has open — it does not touch their main profile
and does not require closing anything). Tell the user plainly:

> 新弹出的那个 Edge 窗口里，请登录你的 LinkedIn 账号；登录后脚本会自动导出 cookies。

The profile persists, so after the first login this step usually exports instantly
with no user action. The script exits non-zero if no login is detected within the
timeout — if that happens, the window likely opened behind other windows or the
user didn't log in; re-run and ask them to look for the new window.

### Step 2 — Download

```bash
python scripts/download_video.py "<POST_URL>" --out "<OUTPUT_DIR>" --name "<basename>"
```

Downloaded LinkedIn videos go to `E:\LinkedIn视频下载` by default (this user's
chosen location for LinkedIn downloads — do not use the dated Work\Claude session
folder for these). Pass `--out` only to override. Use `--name` for a short
descriptive base name (no extension). The script fetches the page, extracts the
signed HLS master, and runs yt-dlp with the right headers. Output is `<basename>.mp4`.

### Step 3 — Verify and open

Confirm the file is real before declaring success (a 0-byte or truncated file means
the signature expired mid-download — refresh cookies and retry):

```bash
ffprobe -v error -show_entries format=duration,size:stream=width,height,codec_name \
  -of default=noprint_wrappers=1 "<OUTPUT_DIR>/<basename>.mp4"
```

Then open it for the user (Edge/PowerShell, per global rules) and give the full
Windows path in a code block.

## Troubleshooting

- **HTTP 451 / 401 when fetching the page** → cookies expired. Re-run `export_cookies.py`.
- **HTTP 403 from dms.licdn.com** → the signed URL expired (they're short-lived) or a query param was dropped. Re-run `download_video.py` (it re-fetches a fresh signed URL each time); if still failing, refresh cookies.
- **"没找到视频播放列表"** → the post may have no video, or be an image/article. Confirm the post actually contains a video.
- **yt-dlp not found** → `python -m pip install -U yt-dlp`. The script invokes it as `python -m yt_dlp`, so a module install is enough.
- **Login never detected** → the dedicated Edge window opened behind other windows. Ask the user to find the newly-opened Edge window (it starts on the LinkedIn login page) and log in there.

## Scope and routing

`download_video.py` auto-routes by URL:
- **linkedin.com** → the cookie + signed-HLS flow described above.
- **anything else** (YouTube, Vimeo, Twitter/X, etc.) → straight to `yt-dlp`, no
  cookies needed, since yt-dlp supports those sites natively and better than any
  scraping. So the user can hand any video URL to this one entry point.

Caveat for public sites: YouTube/Vimeo are frequently blocked on mainland-China
networks. If a public download fails with connection errors, it's a network/GFW
issue, not the skill — set a proxy and retry:
`export HTTPS_PROXY=http://127.0.0.1:<port>` (the script passes it through to yt-dlp).
