import asyncio
from playwright.async_api import async_playwright

async def run():
    url = "https://dexscreener.com/ethereum/0x0000000000000000000000000000000000000000?embed=1"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1000, "height": 600})
        await page.goto(url, timeout=20000)
        await page.wait_for_timeout(5000)  # wait for chart to load
        await page.screenshot(path="test_chart.png")
        await browser.close()

asyncio.run(run())
