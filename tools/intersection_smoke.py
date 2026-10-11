"""Browser checks for a running optional intersection instance (installed Chrome)."""
from pathlib import Path
import argparse
import json
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--out", default="runs/intersection-qa")
    parser.add_argument("--photoreal", action="store_true")
    args = parser.parse_args()
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    errors, requests, checks = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("response", lambda r: requests.append(f"{r.status} {r.url}") if r.status >= 400 else None)
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('#phase-name').textContent !== 'Starting…'")
        assert page.title() == "òcio · Intersection Lab"
        assert page.locator("#scene canvas").count() == 1
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator(".topbar").bounding_box()["y"] + page.locator(".topbar").bounding_box()["height"] <= page.locator(".scene-panel").bounding_box()["y"]
        page.wait_for_function("parseInt(document.querySelector('#agent-count').textContent) > 0")
        page.screenshot(path=str(output / "desktop.png"), full_page=True)
        checks.append("Live 3D canvas, counters and desktop layout")
        for view in ("top", "street", "cinema", "orbit"):
            page.click(f'[data-view="{view}"]')
            assert "on" in page.locator(f'[data-view="{view}"]').get_attribute("class")
        for layer in ("routes", "labels", "trails"):
            page.click(f'[data-layer="{layer}"]')
        checks.append("Four camera views and route/label/trail layers")
        page.click("#pause")
        page.wait_for_function("document.querySelector('#pause').textContent === 'Resume'")
        before = page.locator("#clock").inner_text()
        page.wait_for_timeout(700)
        assert page.locator("#clock").inner_text() == before
        page.click("#pause")
        page.wait_for_function("document.querySelector('#pause').textContent === 'Pause'")
        page.select_option("#policy", "fixed")
        page.wait_for_function("document.querySelector('#policy').value === 'fixed'")
        page.select_option("#policy", "adaptive")
        page.select_option("#crossing", "E")
        page.click("#call")
        page.click("#slow")
        checks.append("Pause/resume, policy change, crossing call and slow walker")
        if args.photoreal:
            assert page.locator("#camera-card").is_visible()
            page.wait_for_function("document.querySelector('#camera-image').naturalWidth === 640")
            page.select_option("#camera-select", "N")
            page.wait_for_function("document.querySelector('#camera-status').textContent.includes('Real YOLO · N')",timeout=60000)
            page.uncheck("#camera-boxes")
            page.wait_for_function("document.querySelector('#camera-image').src.includes('camera-raw.jpg')")
            page.screenshot(path=str(output / "photoreal.png"), full_page=True)
            page.uncheck("#camera-visible")
            assert not page.locator("#pixel-view").is_visible()
            assert page.locator("#scene canvas").is_visible()
            page.check("#camera-visible")
            state=page.evaluate("async()=>await(await fetch('/api/state')).json()")
            assert state["observation_mode"]=="vision" and state["camera"]["active_cameras"]==["N","E","S","W"]
            checks.append("Four-camera NN fusion, separate RGB card, camera switch and raw/overlay/visibility toggles")
        for width in (390, 320):
            page.set_viewport_size({"width": width, "height": 844})
            page.wait_for_timeout(250)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            header, controls = page.locator(".topbar").bounding_box(), page.locator(".actions").bounding_box()
            assert controls["y"] + controls["height"] <= header["y"] + header["height"]
            page.screenshot(path=str(output / f"phone-{width}.png"), full_page=True)
        checks.append("390px and 320px layouts without horizontal overflow")
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.select_option("#scenario", "turning")
        page.wait_for_function("document.querySelector('#scenario').value === 'turning'")
        if args.photoreal:
            page.wait_for_function("async () => {const s=await(await fetch('/api/state')).json();return s.camera && s.camera.generation>0 && s.camera.frame_t<=s.t && s.camera.frame_t<5;}",timeout=60000)
        checks.append("Scenario restart")
        page.click("#compare")
        page.wait_for_function("document.querySelector('#comparison .compare-row') !== null", timeout=120000)
        assert page.locator("#comparison .compare-row").count() == 2
        assert page.locator("#comparison a[download]").count() == 1
        with page.expect_download() as pending:
            page.locator("#comparison a[download]").click()
        download = pending.value
        download.save_as(str(output / "comparison-download.json"))
        report = json.loads((output / "comparison-download.json").read_text(encoding="utf-8"))
        assert report["arrivals_identical"] and report["scenario"] == "turning"
        assert {row["policy"] for row in report["runs"]} == {"fixed", "adaptive"}
        with page.expect_download() as pending:
            page.click("#export")
        pending.value.save_as(str(output / "run-download.json"))
        report = json.loads((output / "run-download.json").read_text(encoding="utf-8"))
        assert report["scenario"] == "turning" and "vehicle_speed_kmh" in report
        checks.append("Background paired policy comparison and JSON download")
        page.screenshot(path=str(output / "comparison.png"), full_page=True)
        browser.close()
    result = {"checks": checks, "javascript_errors": errors, "http_errors": requests}
    (output / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    assert not errors and not requests


if __name__ == "__main__":
    main()
