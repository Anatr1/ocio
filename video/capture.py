"""Record dashboard footage for the submission video with Playwright (1920x1080 webm per segment).
python capture.py NAME   (photoreal | site | citizen | intersection | planner | share)"""
import asyncio
import shutil
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "raw"
OUT.mkdir(exist_ok=True)
W, H = 1920, 1080


async def click(page, sel):
    try:
        await page.click(sel, timeout=3000)
    except Exception as e:  # noqa: BLE001
        print("click failed", sel, e)


async def photoreal(page):
    await page.goto("http://localhost:8004/")
    await page.wait_for_timeout(6000)
    await page.select_option("#mode", "beacon")
    await click(page, 'button[data-layer="video"]')
    await click(page, 'button[data-layer="gt"]')
    await page.wait_for_timeout(8000)
    await click(page, "#btn-nearmiss")
    await page.wait_for_timeout(14000)
    await click(page, 'button[data-view="cinema"]')
    await page.wait_for_timeout(8000)
    await click(page, "#btn-nearmiss")
    await page.wait_for_timeout(14000)
    await click(page, 'button[data-view="orbit"]')
    await page.select_option("#mode", "adaptive")
    await click(page, "#btn-elderly")
    await page.wait_for_timeout(20000)


async def photocam(page):
    await page.set_content('<html><body style="margin:0;background:#000"><img src="http://localhost:8004/video.mjpg" '
                           'style="width:100vw;height:100vh;object-fit:cover"></body></html>')
    await page.wait_for_timeout(16000)


async def intercam(page):
    await page.set_content('<html><body style="margin:0;background:#000"><img id="c" style="width:100vw;height:100vh;object-fit:cover">'
                           '<script>setInterval(()=>{const i=new Image();i.onload=()=>document.getElementById("c").src=i.src;'
                           'i.src="http://localhost:8010/api/camera.jpg?t="+Date.now()},150)</script></body></html>')
    await page.wait_for_timeout(20000)


async def site(page):
    await page.goto("http://localhost:8005/")
    await page.wait_for_timeout(5000)
    await click(page, 'button[data-layer="video"]')
    await page.wait_for_timeout(30000)
    await click(page, 'button[data-view="top"]')
    await page.wait_for_timeout(15000)
    await click(page, 'button[data-view="cinema"]')
    await page.wait_for_timeout(20000)


async def citizen(page):
    await page.goto("http://localhost:8004/public/")
    await page.wait_for_timeout(6000)
    for _ in range(8):
        await page.mouse.wheel(0, 350)
        await page.wait_for_timeout(1200)
    await page.wait_for_timeout(2000)


async def intersection(page):
    await page.goto("http://localhost:8010/")
    await page.wait_for_timeout(40000)


async def planner(page):
    await page.goto("https://ocio-turin-planner.sabbatinienrico00.chatgpt.site/")
    await page.wait_for_timeout(5000)
    try:
        await page.get_by_text("Road basemap").first.click(timeout=3000)
    except Exception as e:  # noqa: BLE001
        print("basemap toggle failed", e)
    await page.wait_for_timeout(3000)
    for label in ("Run", "Esegui", "Calcola"):
        try:
            await page.get_by_role("button", name=label).first.click(timeout=2000)
            break
        except Exception:  # noqa: BLE001
            pass
    await page.wait_for_timeout(8000)
    for _ in range(10):
        await page.mouse.wheel(0, 400)
        await page.wait_for_timeout(1500)


async def share(page):
    await page.goto("http://localhost:8004/")
    await page.wait_for_timeout(5000)
    await click(page, "#btn-share")
    await page.wait_for_timeout(7000)


async def citizen_mobile(page):
    await page.goto("http://localhost:8004/public/")
    await page.wait_for_timeout(4000)
    for _ in range(9):
        await page.mouse.wheel(0, 260)
        await page.wait_for_timeout(1000)


async def main(name):
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", args=["--force-device-scale-factor=1"])
        w, h = (434, 924) if name == "citizen_mobile" else (W, H)
        ctx = await browser.new_context(viewport={"width": w, "height": h}, is_mobile=name == "citizen_mobile",
                                        record_video_dir=str(OUT / name), record_video_size={"width": w, "height": h})
        page = await ctx.new_page()
        await globals()[name](page)
        path = await page.video.path()
        await ctx.close()
        await browser.close()
        shutil.move(path, OUT / f"{name}.webm")
        print("saved", OUT / f"{name}.webm")


asyncio.run(main(sys.argv[1]))
