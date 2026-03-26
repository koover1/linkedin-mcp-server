"""Launch a headed Chromium with the LinkedIn MCP profile for manual inspection."""
import asyncio
from pathlib import Path
from patchright.async_api import async_playwright


async def main():
    p = await async_playwright().start()
    profile_dir = str(Path.home() / ".linkedin-mcp" / "profile")
    print(f"Launching headed browser with profile: {profile_dir}")
    context = await p.chromium.launch_persistent_context(
        profile_dir,
        headless=False,
        viewport={"width": 1400, "height": 900},
    )
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto("https://www.linkedin.com/in/renekton-main-28790a3b9/")
    print("Browser is open. Close the browser window when done.")
    try:
        # Keep alive until browser is closed
        while True:
            await asyncio.sleep(1)
            if len(context.pages) == 0:
                break
    except Exception:
        pass
    await context.close()
    await p.stop()
    print("Browser closed.")


asyncio.run(main())
