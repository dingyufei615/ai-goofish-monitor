import asyncio
import os

from playwright.async_api import async_playwright

# Define the file path for saving the login state
STATE_FILE = "xianyu_state.json"
LOGIN_IS_EDGE = os.getenv("LOGIN_IS_EDGE", "false").lower() == "true"
RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"


async def main():
    async with async_playwright() as p:
        # Launch a non-headless browser so you can see the interface and interact
        # 'channel="msedge"' specifies using the Edge browser
        if LOGIN_IS_EDGE:
            browser = await p.chromium.launch(headless=False, channel="msedge")
        else:
            # Inside a Docker environment, use Playwright's built-in chromium; locally, use the system-installed Chrome
            if RUNNING_IN_DOCKER:
                browser = await p.chromium.launch(headless=False)
            else:
                browser = await p.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context()
        page = await context.new_page()

        # Open the Xianyu homepage, which usually redirects to the login page or shows a login entry point
        await page.goto("https://www.goofish.com/")

        print("\n" + "="*50)
        print("Please manually log in to your Xianyu account in the opened browser window.")
        print("Using the app to scan the QR code is recommended.")
        print("After successful login, come back here and press the Enter key to continue...")
        print("="*50 + "\n")

        # --- This is the modified part ---
        # Use loop.run_in_executor to replace asyncio.to_thread for compatibility with Python 3.8
        loop = asyncio.get_running_loop()
        # The first argument 'None' tells it to use the default thread pool executor.
        # The second argument is the blocking function to run.
        await loop.run_in_executor(None, input)
        # --- End of modification ---

        # After the user confirms login, save the storage state of the current context to a file
        # This will save Cookies, localStorage, etc.
        await context.storage_state(path=STATE_FILE)

        print(f"Login state has been successfully saved to file: {STATE_FILE}")
        await browser.close()

if __name__ == "__main__":
    print("Launching browser for login...")
    asyncio.run(main())
