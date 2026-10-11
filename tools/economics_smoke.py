"""Browser regression checks for the local planner; uses installed Chrome."""
from pathlib import Path
import json

from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parents[1] / "runs" / "economics-qa"


def canvas_has_pixels(page, selector):
    return page.locator(selector).evaluate("""canvas => {
        const data = canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
        let nonempty=0; for(let i=3;i<data.length;i+=4)if(data[i])nonempty++;
        return nonempty>1000;
    }""")


def run():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"errors": [], "checks": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.on("pageerror", lambda e: report["errors"].append(str(e)))
        page.goto("http://127.0.0.1:8020", wait_until="networkidle")
        page.wait_for_function("document.getElementById('selection-count').textContent === '8 districts'")
        assert page.title() == "\u00f2cio | Turin Deployment Planner"
        assert page.locator('.brand strong').inner_text() == "\u00f2cio"
        assert page.locator('footer').inner_text().startswith("\u00f2cio Deployment Lab")
        report['checks'].append('Accented lowercase brand renders in title, header and footer')
        assert canvas_has_pixels(page, "#map canvas")
        assert page.locator("#notice").is_hidden()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator('[name="traffic_level"]').count() == 3
        assert page.locator('[name="priority"]').count() == 2
        assert page.locator('[name="priority"]:checked').input_value() == 'co2'
        assert page.locator('#vehicle_vph').count() == 0
        assert page.locator('#cost_profile').is_hidden()
        assert page.locator('#fixed_green_s').is_hidden()
        assert page.locator('#deployment input[type=number]').count() == 1
        assert page.locator('#inventory_mode').count() == 0
        assert page.locator('#sites_per_10k').count() == 0
        assert page.evaluate('pValues().inventory_mode') == 'mapped'
        full_count = int(page.locator('#proposed-sites').inner_text().replace(',', ''))
        page.fill('#coverage_pct', '50')
        assert page.locator('#coverage-range').input_value() == '50'
        assert int(page.locator('#proposed-sites').inner_text().replace(',', '')) < full_count
        page.locator('#coverage-range').fill('25')
        assert page.locator('#coverage_pct').input_value() == '25'
        page.fill('#coverage_pct', '100')
        for level, expected in [('peak',1128),('light',107),('medium',626)]:
            page.locator(f'.traffic-option:has(input[value="{level}"])').click()
            assert page.evaluate('pValues().vehicle_vph') == expected
        page.click('[data-view="settings"]')
        assert page.locator('#fixed_green_s').is_visible()
        assert '1,135' in page.locator('#cost-preset-summary').inner_text()
        page.select_option('#cost_profile', 'production')
        assert '3,309' in page.locator('#cost-preset-summary').inner_text()
        assert page.locator('#platform_cost_eur').input_value() == '50000'
        assert page.locator('#maintenance_fee_eur').input_value() == '150.00'
        page.select_option('#cost_profile', 'pilot')
        assert page.locator('#installed_price_eur').input_value() == '1135.39'
        assert page.locator('#maintenance_fee_eur').input_value() == '100.00'
        assert page.locator('#replacement_fraction').input_value() == '10'
        assert '1% per year' in page.locator('#replacement-note').inner_text()
        page.fill('#installed_price_eur', '0')
        assert page.evaluate('pValues().installed_cost_eur') == 0
        page.fill('#installed_price_eur', '300')
        page.fill('#platform_cost_eur', '1200')
        page.fill('#maintenance_fee_eur', '20')
        page.fill('#supplier_gross_margin', '40')
        assert page.evaluate('pValues().installed_cost_eur') == 180
        assert '300' in page.locator('#cost-preset-summary').inner_text()
        page.fill('#supplier_gross_margin', '20')
        assert page.evaluate('pValues().installed_cost_eur') == 240
        page.select_option('#baseline', 'beacon')
        page.screenshot(path=str(OUTPUT / 'desktop-settings.png'), full_page=True)
        page.click('[data-view="deployment"]')
        page.select_option('#area-preset', 'district-1')
        page.click('#run')
        page.wait_for_function("lastResult?.parameters.installed_cost_eur === 240 && busy === false", timeout=90000)
        assert page.evaluate('lastResult.totals.installed_sale_price_eur') == 300
        assert page.evaluate('lastResult.totals.capital_eur === lastResult.totals.sites * 300 + 1200')
        assert page.evaluate('lastResult.areas.every(a => a.capital_eur === a.sites * 300)')
        assert page.evaluate('lastResult.totals.annual_service_fee_eur') == 20
        assert page.evaluate('lastResult.totals.replacement_budget_eur === lastResult.totals.sites * .1 * 300')
        assert page.evaluate('lastResult.totals.average_annual_replacement_eur === lastResult.totals.replacement_budget_eur / 10')
        assert page.evaluate('lastResult.totals.gdp_scenario_eur') == 0
        report['checks'].append('Entered EUR300 installed price is used exactly; EUR1200 shared setup charged once, margin not added')
        page.click('#reset')
        assert page.locator('#installed_price_eur').input_value() == '1135.39'
        assert page.locator('#platform_cost_eur').input_value() == '2000'
        page.click('[data-view="settings"]')
        assert page.locator('#spending_additionality').input_value() == '0'
        page.fill('#work_time_fraction', '80')
        page.fill('#spending_time_fraction', '80')
        page.click('#run-top')
        assert 'no more than 100%' in page.locator('#notice').inner_text()
        for key, value in [('work_time_fraction','50'),('spending_time_fraction','50'),('productivity_realization','100'),('labour_value_eur_h','30'),('spending_additionality','25')]:
            page.fill('#'+key, value)
        page.click('[data-view="deployment"]')
        page.screenshot(path=str(OUTPUT / "desktop-deployment.png"), full_page=True)
        report['checks'].append('Simple main page: three traffic choices, synced numeric percentage, separate settings, cost profiles')
        report["checks"].append("Eight official Turin city districts; nonblank map and quota")
        point = page.evaluate("() => { const a=dataset.features[0].properties; const p=map.latLngToContainerPoint([a.center[1],a.center[0]]); return {x:p.x,y:p.y}; }")
        page.locator("#map").click(position=point)
        assert page.locator("#selection-count").inner_text() == "7 districts"
        page.select_option("#area-preset", "district-1")
        assert page.locator("#selection-count").inner_text() == "1 district"
        page.select_option("#area-preset", "all")
        assert page.locator("#selection-count").inner_text() == "8 districts"
        page.click("#run")
        page.wait_for_function("document.getElementById('results-body').hidden === false", timeout=90000)
        page.wait_for_function("busy === false")
        assert page.locator("#results-table tbody tr").count() == 8
        assert canvas_has_pixels(page, "#benefit-chart")
        assert canvas_has_pixels(page, "#cashflow-chart")
        assert canvas_has_pixels(page, "#scale-chart")
        assert canvas_has_pixels(page, "#delay-chart")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUTPUT / "desktop-results.png"), full_page=True)
        report["checks"].append("All-city simulation returns8district rows and4nonblank charts")
        page.click("#save-scenario")
        assert page.locator("#comparison-table tbody tr").count() == 1
        with page.expect_download() as download:
            page.click("#export-json")
        assert download.value.suggested_filename.startswith('ocio-')
        download.value.save_as(str(OUTPUT / "scenario.json"))
        result = json.loads((OUTPUT / "scenario.json").read_text())
        assert result["totals"]["gdp_increase_eur"] is None
        assert abs(result['totals']['gdp_scenario_eur'] - result['totals']['person_hours'] * 15.625) < 1e-6
        assert abs(sum(a['gdp_scenario_eur'] for a in result['areas']) - result['totals']['gdp_scenario_eur']) < 1e-6
        assert result['parameters']['replacement_fraction'] == .1
        assert result['parameters']['replacement_schedule'] == 'spread'
        assert abs(sum(row.get('replacement_eur',0) for row in result['totals']['cashflows']) - result['totals']['replacement_budget_eur']) < 1e-6
        assert 'gdp_assumptions.json' in result['provenance']
        assert page.locator('#gdp-section').is_visible()
        assert page.locator('#lifecycle-metrics').is_visible()
        report['checks'].append('Work/spending GDP scenario reconciles with signed time and district sums; 10% cumulative replacements included in cash flows')
        assert result["totals"]["sites"] == sum(a["sites"] for a in result["areas"])
        assert "provenance" in result
        assert result['parameters']['vehicle_vph'] == 626
        assert result['parameters']['cost_profile'] == 'pilot'
        assert abs(result['parameters']['installed_cost_eur'] - 908.312) < 1e-8
        assert abs(result['totals']['installed_sale_price_eur'] - 1135.39) < 1e-8
        assert result['inventory']['coverage_pct'] == 100
        assert result['totals']['sites'] == full_count
        assert 'traffic_presets.json' in result['provenance']
        assert 'cost_profiles.json' in result['provenance']
        with page.expect_download() as download:
            page.click("#export-csv")
        assert download.value.suggested_filename == 'ocio-turin-districts.csv'
        download.value.save_as(str(OUTPUT / "districts.csv"))
        report["checks"].append("Scenario comparison, full-provenance JSON, and CSV download")
        assert result['parameters']['priority'] == 'co2'
        assert result['totals']['net_co2_tonnes'] > 0
        assert result['totals']['baseline_idle_fuel_litres'] > result['totals']['adaptive_idle_fuel_litres']
        assert page.locator('#fuel-metrics').is_visible()
        page.click('[data-view="deployment"]')
        page.locator('.traffic-option:has(input[name="priority"][value="time"])').click()
        page.click('#run')
        page.wait_for_function("lastResult.parameters.priority === 'time' && busy === false", timeout=90000)
        assert page.evaluate('lastResult.optimization[0].co2_guardrail_met && lastResult.totals.net_co2_tonnes >= 0')
        assert page.evaluate('lastResult.totals.net_co2_tonnes') <= result['totals']['net_co2_tonnes']
        assert page.evaluate('lastResult.totals.person_hours') >= result['totals']['person_hours']
        page.screenshot(path=str(OUTPUT / 'desktop-time-priority.png'), full_page=True)
        report['checks'].append('Real CO2 timing optimization and Time priority with net CO2 guardrail; transparent fuel totals')
        for traffic in ('light', 'peak'):
            results = {}
            for priority in ('co2', 'time'):
                page.click('[data-view="deployment"]')
                page.locator(f'.traffic-option:has(input[name="traffic_level"][value="{traffic}"])').click()
                page.locator(f'.traffic-option:has(input[name="priority"][value="{priority}"])').click()
                previous_id = page.evaluate('lastResult.id')
                page.click('#run')
                page.wait_for_function('id => lastResult.id !== id && busy === false', arg=previous_id, timeout=90000)
                results[priority] = page.evaluate('lastResult')
                assert results[priority]['totals']['person_hours'] > 0
                assert results[priority]['totals']['net_co2_tonnes'] > 0
                assert '626 schedules' in page.locator('#optimization-summary').inner_text()
                assert 'Night:' in page.locator('#timing-detail').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(OUTPUT / f'desktop-{traffic}-{priority}.png'), full_page=True)
            assert results['co2']['totals']['net_co2_tonnes'] > results['time']['totals']['net_co2_tonnes']
            assert results['time']['totals']['person_hours'] > results['co2']['totals']['person_hours']
            report['checks'].append(f'{traffic.title()} traffic: positive time/CO2 savings, distinct priority schedules, timing details render')
        page.set_viewport_size({'width': 320, 'height': 640})
        page.wait_for_timeout(300)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(OUTPUT / 'narrow-timing-results.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.click('[data-view="deployment"]')
        page.select_option("#area-preset", "district-1")
        assert page.locator("#proposed-sites").inner_text() == page.evaluate("new Intl.NumberFormat('en-GB').format(Math.floor(dataset.features.find(f=>f.properties.zone===1).properties.signalized_crossings*.25+.5))")
        page.click('[data-view="settings"]')
        page.select_option("#baseline", "beacon")
        page.click('[data-view="deployment"]')
        page.click("#run")
        page.wait_for_function("lastResult.parameters.baseline === 'beacon' && busy === false", timeout=90000)
        assert page.evaluate("lastResult.totals.npv_eur < 0 && lastResult.totals.net_co2_tonnes < 0")
        report["checks"].append("Mapped-node factor and honest zero-benefit beacon scenario")
        page.click('[data-view="sources"]')
        assert page.locator("#source-list .source-row").count() > 10
        assert page.locator("#bom-table tbody tr").count() >= 17
        page.screenshot(path=str(OUTPUT / "desktop-sources.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.click('[data-view="deployment"]')
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert canvas_has_pixels(page, "#map canvas")
        page.screenshot(path=str(OUTPUT / "mobile-deployment.png"), full_page=True)
        page.click('[data-view="results"]')
        page.wait_for_timeout(400)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUTPUT / "mobile-results.png"), full_page=True)
        report["checks"].append("Mobile390px map and results without document overflow")
        page.set_viewport_size({"width": 320, "height": 640})
        page.wait_for_timeout(400)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        report["checks"].append("Narrow320px results layout")
        page.click('[data-view="deployment"]')
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUTPUT / 'narrow-deployment.png'), full_page=True)
        for level in ['peak','medium','light']:
            page.locator(f'.traffic-option:has(input[value="{level}"])').click()
        page.click('[data-view="settings"]')
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUTPUT / 'narrow-settings.png'), full_page=True)
        page.click('[data-view="deployment"]')
        page.click("#clear")
        assert page.locator("#run").is_disabled()
        page.click("#reset")
        assert page.locator("#selection-count").inner_text() == "8 districts"
        assert page.locator("#run").is_enabled()
        report["checks"].append("Empty-selection guard and reset")
        browser.close()
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    assert not report["errors"]


if __name__ == "__main__":
    run()
