#!/usr/bin/env python3
"""
Download a LinkedIn post video.

LinkedIn gates post pages behind login (returns HTTP 451 when anonymous) and
serves video only as signed HLS (no direct progressive MP4). This script:
  1. Loads previously-exported LinkedIn cookies (see export_cookies.py).
  2. Fetches the post HTML with those cookies.
  3. Extracts the *full* signed HLS master-playlist URL. The signature lives in
     the query string (e=<expiry>&v=beta&t=<token>); a truncated URL returns 403,
     so we must keep every query parameter intact.
  4. Hands the master URL to yt-dlp with a linkedin.com Referer (dms.licdn.com
     rejects requests without it) to download and mux the best quality.

Usage:
    python download_video.py <post_url> --out <output_dir> [--cookies <path>] [--name <basename>]
"""
import argparse, gzip, http.cookiejar, os, re, subprocess, sys, urllib.request

sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")


def unescape(u: str) -> str:
    return u.replace("\\u0026", "&").replace("\\/", "/").replace("&amp;", "&")


def fetch_page(url: str, opener) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9",
                                               "Accept-Encoding": "gzip"})
    resp = opener.open(req, timeout=60)
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def find_master_url(html: str):
    """Return the signed HLS master playlist URL (dynamic playlist), or None."""
    # The master is a '.../playlist/vid/dynamic/...' URL. Capture it with its
    # FULL query string: continue through &-escaped ampersands, stop at a
    # real quote or backslash-quote. Dropping any query param breaks the signature.
    candidates = []
    for m in re.finditer(
        r'https:(?:\\?/){2}dms\.licdn\.com(?:\\?/)playlist(?:\\?/)vid(?:\\?/)dynamic[^"\\]+(?:\\u0026[^"\\]+)*',
        html,
    ):
        candidates.append(unescape(m.group(0)))
    if candidates:
        # Prefer the one carrying a token (t=...) — that's the valid signed form.
        signed = [c for c in candidates if "t=" in c]
        return (signed or candidates)[0]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("post_url")
    ap.add_argument("--out", default=os.path.join(os.path.expanduser("~"), "Downloads", "linkedin-videos"),
                    help="output directory (default: ~/Downloads/linkedin-videos)")
    ap.add_argument("--cookies", default=None, help="cookies.txt path")
    ap.add_argument("--name", default=None, help="output basename (no extension)")
    args = ap.parse_args()

    # Public sites (YouTube/Vimeo/Twitter/etc.) need no login — yt-dlp handles
    # them natively and better than any HTML scraping. Route those straight to
    # yt-dlp and skip the whole cookie/HLS-signature dance.
    if "linkedin.com" not in args.post_url.lower():
        os.makedirs(args.out, exist_ok=True)
        name_tmpl = (args.name + ".%(ext)s") if args.name else "%(title).80s.%(ext)s"
        outtmpl = os.path.join(args.out, name_tmpl)
        print(f"[公开站点] 直接用 yt-dlp 下载 -> {args.out}")
        cmd = [sys.executable, "-m", "yt_dlp", "--no-update",
               "--merge-output-format", "mp4", "-o", outtmpl, args.post_url]
        # If a proxy is set (YouTube/Vimeo are often blocked in CN), honor it.
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("ALL_PROXY")
        if proxy:
            cmd += ["--proxy", proxy]
            print(f"       (使用代理 {proxy})")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print("[ERROR] yt-dlp 下载失败。若是 YouTube/Vimeo 等被墙站点，"
                  "请设置代理：export HTTPS_PROXY=http://127.0.0.1:端口")
            sys.exit(r.returncode)
        print(f"\n[OK] 下载完成，保存在: {args.out}")
        return

    here = os.path.dirname(os.path.abspath(__file__))
    default_cookies = os.path.join(here, "..", "linkedin_cookies.txt")
    cookies_path = args.cookies or os.environ.get("LINKEDIN_COOKIES") or default_cookies
    cookies_path = os.path.abspath(cookies_path)

    if not os.path.exists(cookies_path):
        print(f"[ERROR] 找不到 cookies 文件: {cookies_path}")
        print("请先运行 export_cookies.py 登录并导出 cookies。")
        sys.exit(2)

    cj = http.cookiejar.MozillaCookieJar(cookies_path)
    cj.load(ignore_discard=True, ignore_expires=True)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    print(f"[1/3] 用 cookies 抓取帖子页面...")
    try:
        html = fetch_page(args.post_url, opener)
    except urllib.error.HTTPError as e:
        if e.code in (451, 401, 403, 999):
            print(f"[ERROR] HTTP {e.code} —— cookies 可能已过期或未登录。")
            print("请重新运行 export_cookies.py 刷新 cookies。")
            sys.exit(3)
        raise
    print(f"       页面长度 {len(html):,} 字符")

    master = find_master_url(html)
    if not master:
        print("[ERROR] 页面里没找到视频播放列表。可能该帖子没有视频，或页面结构变化。")
        sys.exit(4)
    print(f"[2/3] 找到视频主播放列表（含签名）")

    os.makedirs(args.out, exist_ok=True)
    basename = args.name or "linkedin_video"
    outtmpl = os.path.join(args.out, basename + ".%(ext)s")

    print(f"[3/3] yt-dlp 下载中 -> {args.out}")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--cookies", cookies_path,
        "--add-header", f"Referer:{args.post_url}",
        "--add-header", "Origin:https://www.linkedin.com",
        "--add-header", f"User-Agent:{UA}",
        "--merge-output-format", "mp4",
        "--no-update",
        "-o", outtmpl,
        master,
    ]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("[ERROR] yt-dlp 下载失败。若报 403，可能签名已过期，请刷新 cookies 后重试。")
        sys.exit(r.returncode)

    print(f"\n[OK] 下载完成，保存在: {args.out}")


if __name__ == "__main__":
    main()
