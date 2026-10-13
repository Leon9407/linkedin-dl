#!/usr/bin/env python3
"""
Export LinkedIn cookies by driving a dedicated Edge instance.

Why this exists: LinkedIn post pages 451 when anonymous, so we need the user's
login cookies. We can't read the main Edge profile's cookie DB while Edge is
running (Edge holds an exclusive lock), and decrypting it via DPAPI is both
fragile and a security-sensitive operation. Instead we launch a SEPARATE Edge
instance with its own profile directory (coexists with the user's running Edge),
let the user log in once, and read cookies straight from Playwright's own browser
context — no file lock, no decryption. The profile persists, so subsequent runs
usually find an existing login and export immediately without re-prompting.

Usage:
    python export_cookies.py [--profile <dir>] [--out <cookies.txt>] [--timeout <seconds>]
"""
import argparse, os, sys, time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[ERROR] 需要 playwright: pip install playwright && playwright install")
    sys.exit(2)

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
LOGIN_URL = "https://www.linkedin.com/login"


def to_netscape(cookies):
    lines = ["# Netscape HTTP Cookie File\n"]
    for c in cookies:
        dom = c["domain"]
        if "linkedin" not in dom:
            continue
        inc = "TRUE" if dom.startswith(".") else "FALSE"
        secure = "TRUE" if c.get("secure") else "FALSE"
        exp = int(c.get("expires") or 0)
        if exp <= 0:
            exp = int(time.time()) + 3600 * 24 * 30
        lines.append(f"{dom}\t{inc}\t{c.get('path','/')}\t{secure}\t{exp}\t{c['name']}\t{c['value']}\n")
    return lines


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.path.join(os.path.expanduser("~"),
                    ".linkedin-video-download", "edge-profile"),
                    help="persistent Edge profile dir (keeps you logged in)")
    ap.add_argument("--out", default=os.path.abspath(os.path.join(here, "..", "linkedin_cookies.txt")))
    ap.add_argument("--timeout", type=int, default=600, help="max seconds to wait for login")
    args = ap.parse_args()

    os.makedirs(args.profile, exist_ok=True)
    print(f"启动独立 Edge 实例（profile: {args.profile}）...")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=args.profile,
            executable_path=EDGE_PATH,
            headless=False,
            args=["--no-first-run", "--no-default-browser-check", "--start-maximized"],
            no_viewport=True,
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            page.bring_to_front()
        except Exception as e:
            print(f"(导航提示: {str(e)[:70]})")

        print("=" * 60)
        print(">>> 若未登录，请在弹出的 Edge 窗口里登录 LinkedIn <<<")
        print("    已登录则会立即导出，无需操作。")
        print("=" * 60)

        exported = False
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            try:
                cookies = ctx.cookies()
                logged_in = any(c["name"] == "li_at" for c in cookies)
            except Exception:
                logged_in = False
            if logged_in:
                time.sleep(3)  # let late cookies settle
                cookies = ctx.cookies()
                lines = to_netscape(cookies)
                with open(args.out, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                print(f"[OK] 已导出 {len(lines)-1} 条 cookies -> {args.out}")
                exported = True
                break
            time.sleep(3)

        ctx.close()
        if not exported:
            print(f"[WARN] {args.timeout} 秒内未检测到登录，未导出。")
            sys.exit(1)


if __name__ == "__main__":
    main()
