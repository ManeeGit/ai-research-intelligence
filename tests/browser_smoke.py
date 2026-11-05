"""Optional browser QA; requires a separately installed Playwright and Chromium."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8765')
parser.add_argument('--chromium', default='/usr/bin/chromium')
parser.add_argument('--screenshot')
args = parser.parse_args()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=args.chromium, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1050}, device_scale_factor=1)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(args.url)
    expect(page.locator('#paper-count')).to_have_text('12')
    expect(page.locator('#notice')).to_contain_text('fictional records')
    if args.screenshot:
        page.screenshot(path=args.screenshot, full_page=True)
    page.locator('nav a[href="#library"]').click()
    expect(page.locator('#library')).to_be_visible()
    page.locator('#library-filter').fill('BM25')
    expect(page.locator('#all-papers .paper-row')).to_have_count(1)
    page.locator('#library-filter').fill('NoSuchPaper999')
    expect(page.locator('#all-papers')).to_contain_text('No papers match')
    page.locator('#library-filter').fill('')
    expect(page.locator('#all-papers .paper-row')).to_have_count(12)
    page.locator('nav a[href="#ask"]').click()
    page.locator('#question').fill('How can exact citation quotes and offsets be verified?')
    page.locator('#ask-button').click()
    expect(page.locator('.evidence-card').first).to_be_visible()
    expect(page.locator('.evidence-meta').first).to_contain_text('Exact source match')
    page.locator('#question').fill('What is the Higgs boson mass?')
    page.locator('#ask-button').click()
    expect(page.locator('#answer-results')).to_contain_text('Not enough evidence')
    page.locator('[data-question]').first.click()
    expect(page.locator('#question')).not_to_have_value('What is the Higgs boson mass?')
    # Delay a request to exercise cancellation and navigation without late UI writes.
    pending_routes = []
    def delayed(route):
        pending_routes.append(route)
    page.route('**/api/answer', delayed)
    page.locator('#ask-button').click()
    page.locator('#cancel-answer').click()
    expect(page.locator('#answer-results')).to_contain_text('Search canceled')
    expect(page.locator('#ask-button')).to_be_enabled()
    page.locator('#ask-button').click()
    page.locator('nav a[href="#brief"]').click()
    expect(page.locator('#brief')).to_be_visible()
    page.wait_for_timeout(700)
    page.locator('nav a[href="#ask"]').click()
    expect(page.locator('#answer-results')).to_contain_text('Search canceled')
    page.unroute('**/api/answer', delayed)
    for route in pending_routes:
        try: route.abort()
        except Exception: pass  # A canceled browser request may already be gone.
    page.go_back()
    expect(page.locator('#brief')).to_be_visible()
    page.go_forward()
    expect(page.locator('#ask')).to_be_visible()
    page.locator('nav a[href="#brief"]').click()
    with page.expect_download() as download:
        page.locator('#download-brief').click()
    assert download.value.suggested_filename.endswith('.md')
    # Text rendering must never execute retrieved HTML.
    page.route('**/api/answer', lambda route: route.fulfill(json={
        'citations': [{'id':'E1','title':'<img src=x onerror=alert(1)>','quote':'<script>alert(1)</script>',
                       'synthetic':True,'start':0,'end':26,'content_hash':'a'*64}],
        'summary':'Untrusted text test','synthetic':True,'limitations':[]}))
    page.locator('nav a[href="#ask"]').click()
    page.locator('#ask-button').click()
    expect(page.locator('.evidence-card h3')).to_contain_text('<img src=x')
    expect(page.locator('#answer-results img')).to_have_count(0)
    expect(page.locator('#answer-results script')).to_have_count(0)
    page.set_viewport_size({'width':390,'height':844})
    page.locator('nav a[href="#overview"]').click()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
    assert not errors, errors
    browser.close()
print('Browser smoke passed: navigation, filters, evidence, abstention, cancellation, history, downloads, XSS, mobile.')
