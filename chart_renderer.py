import os
import asyncio
import logging
from PIL import Image
import aiohttp
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# Maksimal 2 Chromium bersamaan; request chart lain antre, supaya server tidak kehabisan RAM.
_BROWSER_SLOTS = asyncio.Semaphore(int(os.getenv("MAX_PARALLEL_CHARTS", "2")))


def compress_image(path: str, max_size_kb: int = 250) -> str:
    """
    Compress PNG chart ke JPEG supaya <= max_size_kb.
    Return path file hasil kompres.
    """
    try:
        img = Image.open(path).convert("RGB")
        quality = 90
        output_path = path.rsplit(".", 1)[0] + "_compressed.jpg"

        while True:
            img.save(output_path, "JPEG", quality=quality, optimize=True)
            size_kb = os.path.getsize(output_path) / 1024

            if size_kb <= max_size_kb or quality <= 20:
                break
            quality -= 10

        logger.info(f"Chart compressed → {int(size_kb)} KB: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Image compression failed for {path}: {e}")
        return path  # fallback original


class ChartRenderer:
    @staticmethod
    def build_dexscreener_embed_url(chain_id: str, pair_address: str, timeframe: str = "1h") -> str:
        """
        Build Dexscreener embed URL dengan tema dark dan minim toolbar.
        """
        base = f"https://dexscreener.com/{chain_id}/{pair_address}"
        interval_map = {
            '1m': '1', '3m': '3', '5m': '5', '15m': '15', '30m': '30',
            '1h': '60', '2h': '120', '4h': '240', '8h': '480', '12h': '720',
            '1d': '1D', '3d': '3D', '1w': '1W'
        }
        interval = interval_map.get(timeframe, '60')
        embed_params = [
            "embed=1",
            "loadChartSettings=0",
            "chartLeftToolbar=0",
            "chartTheme=dark",
            "theme=dark",
            "chartStyle=1",
            "chartType=usd",
            f"interval={interval}"
        ]
        return f"{base}?{'&'.join(embed_params)}"

    @staticmethod
    def build_dexscreener_url(chain_id: str, pair_address: str, timeframe: str = "1h") -> str:
        """Alias biar backward compatible dengan main.py lama"""
        return ChartRenderer.build_dexscreener_embed_url(chain_id, pair_address, timeframe)

    @staticmethod
    async def fetch_chart_image(url: str, output_path: str) -> str:
        """
        (Deprecated untuk Dexscreener)
        Hanya bisa dipakai kalau URL langsung image (bukan HTML).
        """
        try:
            if os.path.dirname(output_path):
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status != 200:
                        return ""
                    data = await resp.read()
                    with open(output_path, "wb") as f:
                        f.write(data)

            # sanity check
            try:
                Image.open(output_path).verify()
            except Exception:
                return ""
            return output_path
        except Exception:
            return ""

    @staticmethod
    async def screenshot_chart(url: str, output_path: str, max_size_kb: int = 250) -> str:
        """
        Screenshot live chart Dexscreener:
        - headless=True supaya VPS / headless environment bisa jalan
        - set user agent & viewport di BrowserContext
        - tunggu chart render 35 detik
        - ambil canvas terbesar, fallback full-page
        - compress ke JPEG <= max_size_kb
        """
        try:
            async with _BROWSER_SLOTS, async_playwright() as p:
                browser = await p.chromium.launch(headless=True)

                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                    accept_downloads=False
                )

                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                logger.info("⏳ Tunggu 35 detik supaya live chart render...")
                await page.wait_for_timeout(35000)

                # cari canvas terbesar
                biggest = None
                max_area = 0
                for frame in page.frames:
                    canvases = frame.locator("canvas")
                    count = await canvases.count()
                    for i in range(count):
                        box = await canvases.nth(i).bounding_box()
                        if box:
                            area = box["width"] * box["height"]
                            if area > max_area:
                                max_area = area
                                biggest = canvases.nth(i)

                if biggest:
                    await biggest.screenshot(path=output_path)
                    logger.info(f"📸 Canvas terbesar screenshot → {output_path}")
                else:
                    logger.warning("⚠️ Tidak bisa temukan canvas, fallback full screenshot")
                    await page.screenshot(path=output_path, full_page=True)

                await browser.close()

            # compress hasil
            img = Image.open(output_path).convert("RGB")
            quality = 90
            output_jpeg = output_path.rsplit(".", 1)[0] + "_compressed.jpg"
            while True:
                img.save(output_jpeg, "JPEG", quality=quality, optimize=True)
                size_kb = os.path.getsize(output_jpeg) / 1024
                if size_kb <= max_size_kb or quality <= 20:
                    break
                quality -= 10

            logger.info(f"Chart compressed → {int(size_kb)} KB: {output_jpeg}")
            return output_jpeg

        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            return ""
