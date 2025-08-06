import asyncio
import sys
import os
import argparse
import math
import json
import random
import base64
import re
import time
from datetime import datetime
from functools import wraps
from urllib.parse import urlencode, quote

import requests
from dotenv import load_dotenv
from openai import AsyncOpenAI, APIStatusError
from playwright.async_api import async_playwright, Response, TimeoutError as PlaywrightTimeoutError
from requests.exceptions import HTTPError

# Define the file path for the login state
STATE_FILE = "xianyu_state.json"
# Define the URL pattern for the Xianyu search API
API_URL_PATTERN = "h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search"
# Define the URL pattern for the Xianyu detail page API
DETAIL_API_URL_PATTERN = "h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail"

# --- AI & Notification Configuration ---
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("OPENAI_BASE_URL")
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")
PROXY_URL = os.getenv("PROXY_URL")
NTFY_TOPIC_URL = os.getenv("NTFY_TOPIC_URL")
WX_BOT_URL = os.getenv("WX_BOT_URL")
PCURL_TO_MOBILE = os.getenv("PCURL_TO_MOBILE")
RUN_HEADLESS = os.getenv("RUN_HEADLESS", "true").lower() != "false"
LOGIN_IS_EDGE = os.getenv("LOGIN_IS_EDGE", "false").lower() == "true"
RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"
AI_DEBUG_MODE = os.getenv("AI_DEBUG_MODE", "false").lower() == "true"

# Check if the configuration is complete
if not all([BASE_URL, MODEL_NAME]):
    sys.exit("Error: Please ensure that OPENAI_BASE_URL and OPENAI_MODEL_NAME are fully set in the .env file. (OPENAI_API_KEY is optional for some services)")

# Initialize OpenAI client
try:
    if PROXY_URL:
        print(f"Using HTTP/S proxy for AI requests: {PROXY_URL}")
        # httpx automatically reads proxy settings from environment variables
        os.environ['HTTP_PROXY'] = PROXY_URL
        os.environ['HTTPS_PROXY'] = PROXY_URL

    # The httpx client inside the openai client will automatically pick up proxy settings from environment variables
    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
except Exception as e:
    sys.exit(f"Error initializing OpenAI client: {e}")

# Define directories and filenames
IMAGE_SAVE_DIR = "images"
os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)

# Define request headers for downloading images
IMAGE_DOWNLOAD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) Gecko/20100101 Firefox/139.0',
    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

def convert_goofish_link(url: str) -> str:
    """
    Converts a Goofish product link to a mobile-friendly format containing only the product ID.

    Args:
        url: The original Goofish product link.

    Returns:
        The converted concise link, or the original link if it cannot be parsed.
    """
    # Match the product ID pattern in the first link: the number string after item?id=
    match_first_link = re.search(r'item\?id=(\d+)', url)
    if match_first_link:
        item_id = match_first_link.group(1)
        bfp_json = f'{{"id":{item_id}}}'
        return f"https://pages.goofish.com/sharexy?loadingVisible=false&bft=item&bfs=idlepc.item&spm=a21ybx.item.0.0&bfp={quote(bfp_json)}"

    return url

def get_link_unique_key(link: str) -> str:
    """Extracts the content before the first "&" in the link as a unique identifier."""
    return link.split('&', 1)[0]

async def random_sleep(min_seconds: float, max_seconds: float):
    """Asynchronously waits for a random duration within a specified range."""
    delay = random.uniform(min_seconds, max_seconds)
    print(f"   [Delay] Waiting for {delay:.2f} seconds... (Range: {min_seconds}-{max_seconds}s)") # Can be uncommented for debugging
    await asyncio.sleep(delay)

async def save_to_jsonl(data_record: dict, keyword: str):
    """Appends a complete record containing product and seller information to a .jsonl file."""
    output_dir = "jsonl"
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{keyword.replace(' ', '_')}_full_data.jsonl")
    try:
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(data_record, ensure_ascii=False) + "\n")
        return True
    except IOError as e:
        print(f"Error writing to file {filename}: {e}")
        return False

async def calculate_reputation_from_ratings(ratings_json: list) -> dict:
    """Calculates the number and rate of positive reviews as a seller and a buyer from the raw rating API data list."""
    seller_total = 0
    seller_positive = 0
    buyer_total = 0
    buyer_positive = 0

    for card in ratings_json:
        # Use safe_get to ensure safe access
        data = await safe_get(card, 'cardData', default={})
        role_tag = await safe_get(data, 'rateTagList', 0, 'text', default='')
        rate_type = await safe_get(data, 'rate') # 1=Positive, 0=Neutral, -1=Negative

        if "卖家" in role_tag or "Seller" in role_tag:
            seller_total += 1
            if rate_type == 1:
                seller_positive += 1
        elif "买家" in role_tag or "Buyer" in role_tag:
            buyer_total += 1
            if rate_type == 1:
                buyer_positive += 1

    # Calculate ratios, handling division by zero
    seller_rate = f"{(seller_positive / seller_total * 100):.2f}%" if seller_total > 0 else "N/A"
    buyer_rate = f"{(buyer_positive / buyer_total * 100):.2f}%" if buyer_total > 0 else "N/A"

    return {
        "positive_reviews_as_seller": f"{seller_positive}/{seller_total}",
        "positive_rate_as_seller": seller_rate,
        "positive_reviews_as_buyer": f"{buyer_positive}/{buyer_total}",
        "positive_rate_as_buyer": buyer_rate
    }

async def _parse_user_items_data(items_json: list) -> list:
    """Parses the JSON data of the item list API on the user's homepage."""
    parsed_list = []
    for card in items_json:
        data = card.get('cardData', {})
        status_code = data.get('itemStatus')
        if status_code == 0:
            status_text = "For Sale"
        elif status_code == 1:
            status_text = "Sold"
        else:
            status_text = f"Unknown Status ({status_code})"

        parsed_list.append({
            "item_id": data.get('id'),
            "item_title": data.get('title'),
            "item_price": data.get('priceInfo', {}).get('price'),
            "item_main_image": data.get('picInfo', {}).get('picUrl'),
            "item_status": status_text
        })
    return parsed_list


async def scrape_user_profile(context, user_id: str) -> dict:
    """
    [New Version] Visits a specified user's personal homepage and sequentially collects their summary info, full item list, and full rating list.
    """
    print(f"   -> Starting to collect full information for user ID: {user_id}...")
    profile_data = {}
    page = await context.new_page()

    # Prepare Futures and data containers for various async tasks
    head_api_future = asyncio.get_event_loop().create_future()

    all_items, all_ratings = [], []
    stop_item_scrolling, stop_rating_scrolling = asyncio.Event(), asyncio.Event()

    async def handle_response(response: Response):
        # Capture user head summary API
        if "mtop.idle.web.user.page.head" in response.url and not head_api_future.done():
            try:
                head_api_future.set_result(await response.json())
                print(f"      [API Capture] User head info... Success")
            except Exception as e:
                if not head_api_future.done(): head_api_future.set_exception(e)

        # Capture item list API
        elif "mtop.idle.web.xyh.item.list" in response.url:
            try:
                data = await response.json()
                all_items.extend(data.get('data', {}).get('cardList', []))
                print(f"      [API Capture] Item list... Currently captured {len(all_items)} items")
                if not data.get('data', {}).get('nextPage', True):
                    stop_item_scrolling.set()
            except Exception as e:
                stop_item_scrolling.set()

        # Capture rating list API
        elif "mtop.idle.web.trade.rate.list" in response.url:
            try:
                data = await response.json()
                all_ratings.extend(data.get('data', {}).get('cardList', []))
                print(f"      [API Capture] Rating list... Currently captured {len(all_ratings)} ratings")
                if not data.get('data', {}).get('nextPage', True):
                    stop_rating_scrolling.set()
            except Exception as e:
                stop_rating_scrolling.set()

    page.on("response", handle_response)

    try:
        # --- Task 1: Navigate and collect head info ---
        await page.goto(f"https://www.goofish.com/personal?userId={user_id}", wait_until="domcontentloaded", timeout=20000)
        head_data = await asyncio.wait_for(head_api_future, timeout=15)
        profile_data = await parse_user_head_data(head_data)

        # --- Task 2: Scroll to load all items (default page) ---
        print("      [Collection Phase] Starting to collect the user's item list...")
        await random_sleep(2, 4) # Wait for the first page of item API to complete
        while not stop_item_scrolling.is_set():
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            try:
                await asyncio.wait_for(stop_item_scrolling.wait(), timeout=8)
            except asyncio.TimeoutError:
                print("      [Scroll Timeout] Item list might be fully loaded.")
                break
        profile_data["seller_published_items"] = await _parse_user_items_data(all_items)

        # --- Task 3: Click and collect all ratings ---
        print("      [Collection Phase] Starting to collect the user's rating list...")
        rating_tab_locator = page.locator("//div[text()='信用及评价' or text()='Credit & Reviews']/ancestor::li")
        if await rating_tab_locator.count() > 0:
            await rating_tab_locator.click()
            await random_sleep(3, 5) # Wait for the first page of rating API to complete

            while not stop_rating_scrolling.is_set():
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                try:
                    await asyncio.wait_for(stop_rating_scrolling.wait(), timeout=8)
                except asyncio.TimeoutError:
                    print("      [Scroll Timeout] Rating list might be fully loaded.")
                    break

            profile_data['seller_received_ratings'] = await parse_ratings_data(all_ratings)
            reputation_stats = await calculate_reputation_from_ratings(all_ratings)
            profile_data.update(reputation_stats)
        else:
            print("      [Warning] Rating tab not found, skipping rating collection.")

    except Exception as e:
        print(f"   [Error] An error occurred while collecting info for user {user_id}: {e}")
    finally:
        page.remove_listener("response", handle_response)
        await page.close()
        print(f"   -> User {user_id} information collection complete.")

    return profile_data

async def parse_user_head_data(head_json: dict) -> dict:
    """Parses the JSON data from the user head API."""
    data = head_json.get('data', {})
    ylz_tags = await safe_get(data, 'module', 'base', 'ylzTags', default=[])
    seller_credit, buyer_credit = {}, {}
    for tag in ylz_tags:
        if await safe_get(tag, 'attributes', 'role') == 'seller':
            seller_credit = {'level': await safe_get(tag, 'attributes', 'level'), 'text': tag.get('text')}
        elif await safe_get(tag, 'attributes', 'role') == 'buyer':
            buyer_credit = {'level': await safe_get(tag, 'attributes', 'level'), 'text': tag.get('text')}
    return {
        "seller_nickname": await safe_get(data, 'module', 'base', 'displayName'),
        "seller_avatar_link": await safe_get(data, 'module', 'base', 'avatar', 'avatar'),
        "seller_bio": await safe_get(data, 'module', 'base', 'introduction', default=''),
        "seller_items_count": await safe_get(data, 'module', 'tabs', 'item', 'number'),
        "seller_ratings_count": await safe_get(data, 'module', 'tabs', 'rate', 'number'),
        "seller_credit_level": seller_credit.get('text', 'Not available'),
        "buyer_credit_level": buyer_credit.get('text', 'Not available')
    }


async def parse_ratings_data(ratings_json: list) -> list:
    """Parses the JSON data of the rating list API."""
    parsed_list = []
    for card in ratings_json:
        data = await safe_get(card, 'cardData', default={})
        rate_tag = await safe_get(data, 'rateTagList', 0, 'text', default='Unknown Role')
        rate_type = await safe_get(data, 'rate')
        if rate_type == 1: rate_text = "Positive"
        elif rate_type == 0: rate_text = "Neutral"
        elif rate_type == -1: rate_text = "Negative"
        else: rate_text = "Unknown"
        parsed_list.append({
            "rating_id": data.get('rateId'),
            "rating_content": data.get('feedback'),
            "rating_type": rate_text,
            "rater_role": rate_tag,
            "rater_nickname": data.get('raterUserNick'),
            "rating_time": data.get('gmtCreate'),
            "rating_images": await safe_get(data, 'pictCdnUrlList', default=[])
        })
    return parsed_list

async def safe_get(data, *keys, default="Not available"):
    """Safely get a nested dictionary value."""
    for key in keys:
        try:
            data = data[key]
        except (KeyError, TypeError, IndexError):
            return default
    return data

async def _parse_search_results_json(json_data: dict, source: str) -> list:
    """Parses the JSON data from the search API, returning a list of basic item information."""
    page_data = []
    try:
        items = await safe_get(json_data, "data", "resultList", default=[])
        if not items:
            print(f"LOG: ({source}) No item list (resultList) found in API response.")
            if AI_DEBUG_MODE:
                print(f"--- [SEARCH DEBUG] RAW JSON RESPONSE from {source} ---")
                print(json.dumps(json_data, ensure_ascii=False, indent=2))
                print("----------------------------------------------------")
            return []

        for item in items:
            main_data = await safe_get(item, "data", "item", "main", "exContent", default={})
            click_params = await safe_get(item, "data", "item", "main", "clickParam", "args", default={})

            title = await safe_get(main_data, "title", default="Unknown Title")
            price_parts = await safe_get(main_data, "price", default=[])
            price = "".join([str(p.get("text", "")) for p in price_parts if isinstance(p, dict)]).replace("当前价", "").strip() if isinstance(price_parts, list) else "Abnormal Price"
            if "万" in price: price = f"¥{float(price.replace('¥', '').replace('万', '')) * 10000:.0f}"
            area = await safe_get(main_data, "area", default="Unknown Area")
            seller = await safe_get(main_data, "userNickName", default="Anonymous Seller")
            raw_link = await safe_get(item, "data", "item", "main", "targetUrl", default="")
            image_url = await safe_get(main_data, "picUrl", default="")
            pub_time_ts = click_params.get("publishTime", "")
            item_id = await safe_get(main_data, "itemId", default="Unknown ID")
            original_price = await safe_get(main_data, "oriPrice", default="Not available")
            wants_count = await safe_get(click_params, "wantNum", default='NaN')


            tags = []
            if await safe_get(click_params, "tag") == "freeship":
                tags.append("Free Shipping")
            r1_tags = await safe_get(main_data, "fishTags", "r1", "tagList", default=[])
            for tag_item in r1_tags:
                content = await safe_get(tag_item, "data", "content", default="")
                if "验货宝" in content or "Inspection" in content:
                    tags.append("Inspection Service")

            page_data.append({
                "item_title": title,
                "current_price": price,
                "original_price": original_price,
                "wants_count": wants_count,
                "item_tags": tags,
                "location": area,
                "seller_nickname": seller,
                "item_link": raw_link.replace("fleamarket://", "https://www.goofish.com/"),
                "publish_time": datetime.fromtimestamp(int(pub_time_ts)/1000).strftime("%Y-%m-%d %H:%M") if pub_time_ts.isdigit() else "Unknown Time",
                "item_id": item_id
            })
        print(f"LOG: ({source}) Successfully parsed {len(page_data)} basic item infos.")
        return page_data
    except Exception as e:
        print(f"LOG: ({source}) JSON data processing exception: {str(e)}")
        return []

def format_registration_days(total_days: int) -> str:
    """
    Formats the total number of days into a string like "X years Y months".
    """
    if not isinstance(total_days, int) or total_days <= 0:
        return 'Unknown'

    # Use more precise average days
    DAYS_IN_YEAR = 365.25
    DAYS_IN_MONTH = DAYS_IN_YEAR / 12  # Approx 30.44

    # Calculate years
    years = math.floor(total_days / DAYS_IN_YEAR)

    # Calculate remaining days
    remaining_days = total_days - (years * DAYS_IN_YEAR)

    # Calculate months, rounding
    months = round(remaining_days / DAYS_IN_MONTH)

    # Handle carry-over: if months is 12, add 1 to years and set months to 0
    if months == 12:
        years += 1
        months = 0

    # Build the final output string
    if years > 0 and months > 0:
        return f"On Xianyu for {years} years and {months} months"
    elif years > 0 and months == 0:
        return f"On Xianyu for {years} years"
    elif years == 0 and months > 0:
        return f"On Xianyu for {months} months"
    else: # years == 0 and months == 0
        return "On Xianyu for less than a month"


# --- AI Analysis & Notification Helper Functions (ported from ai_filter.py and made async) ---

def retry_on_failure(retries=3, delay=5):
    """
    A generic async retry decorator with detailed logging for HTTP errors.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for i in range(retries):
                try:
                    return await func(*args, **kwargs)
                except (APIStatusError, HTTPError) as e:
                    print(f"Function {func.__name__} failed on attempt {i + 1}/{retries} with an HTTP error.")
                    if hasattr(e, 'status_code'):
                        print(f"  - Status Code: {e.status_code}")
                    if hasattr(e, 'response') and hasattr(e.response, 'text'):
                        response_text = e.response.text
                        print(
                            f"  - Response: {response_text[:300]}{'...' if len(response_text) > 300 else ''}")
                except json.JSONDecodeError as e:
                    print(f"Function {func.__name__} failed on attempt {i + 1}/{retries}: JSON parsing error - {e}")
                except Exception as e:
                    print(f"Function {func.__name__} failed on attempt {i + 1}/{retries}: {type(e).__name__} - {e}")

                if i < retries - 1:
                    print(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)

            print(f"Function {func.__name__} failed definitively after {retries} attempts.")
            return None
        return wrapper
    return decorator


@retry_on_failure(retries=2, delay=3)
async def _download_single_image(url, save_path):
    """An internal function with retries to asynchronously download a single image."""
    loop = asyncio.get_running_loop()
    # Use run_in_executor to run synchronous requests code to avoid blocking the event loop
    response = await loop.run_in_executor(
        None,
        lambda: requests.get(url, headers=IMAGE_DOWNLOAD_HEADERS, timeout=20, stream=True)
    )
    response.raise_for_status()
    with open(save_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return save_path


async def download_all_images(product_id, image_urls):
    """Asynchronously downloads all images for a product. Skips if an image already exists."""
    if not image_urls:
        return []

    urls = [url.strip() for url in image_urls if url.strip().startswith('http')]
    if not urls:
        return []

    saved_paths = []
    total_images = len(urls)
    for i, url in enumerate(urls):
        try:
            clean_url = url.split('.heic')[0] if '.heic' in url else url
            file_name_base = os.path.basename(clean_url).split('?')[0]
            file_name = f"product_{product_id}_{i + 1}_{file_name_base}"
            file_name = re.sub(r'[\\/*?:"<>|]', "", file_name)
            if not os.path.splitext(file_name)[1]:
                file_name += ".jpg"

            save_path = os.path.join(IMAGE_SAVE_DIR, file_name)

            if os.path.exists(save_path):
                print(f"   [Image] Image {i + 1}/{total_images} already exists, skipping download: {os.path.basename(save_path)}")
                saved_paths.append(save_path)
                continue

            print(f"   [Image] Downloading image {i + 1}/{total_images}: {url}")
            if await _download_single_image(url, save_path):
                print(f"   [Image] Image {i + 1}/{total_images} downloaded successfully to: {os.path.basename(save_path)}")
                saved_paths.append(save_path)
        except Exception as e:
            print(f"   [Image] An error occurred while processing image {url}, skipping this image: {e}")

    return saved_paths


def encode_image_to_base64(image_path):
    """Encodes a local image file into a Base64 string."""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        print(f"Error encoding image: {e}")
        return None


@retry_on_failure(retries=3, delay=5)
async def send_ntfy_notification(product_data, reason):
    """Asynchronously sends a high-priority ntfy.sh notification when a recommended product is found."""
    if not NTFY_TOPIC_URL and not WX_BOT_URL:
        print("Warning: NTFY_TOPIC_URL or WX_BOT_URL is not configured in the .env file, skipping notification.")
        return

    title = product_data.get('item_title', 'N/A')
    price = product_data.get('current_price', 'N/A')
    link = product_data.get('item_link', '#')
    if PCURL_TO_MOBILE:
        mobile_link = convert_goofish_link(link)
        message = f"Price: {price}\nReason: {reason}\nMobile Link: {mobile_link}\nPC Link: {link}"
    else:
        message = f"Price: {price}\nReason: {reason}\nLink: {link}"

    notification_title = f"🚨 New Recommendation! {title[:30]}..."

    # --- Send ntfy notification ---
    if NTFY_TOPIC_URL:
        try:
            print(f"   -> Sending ntfy notification to: {NTFY_TOPIC_URL}")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: requests.post(
                    NTFY_TOPIC_URL,
                    data=message.encode('utf-8'),
                    headers={
                        "Title": notification_title.encode('utf-8'),
                        "Priority": "urgent",
                        "Tags": "bell,vibration"
                    },
                    timeout=10
                )
            )
            print("   -> ntfy notification sent successfully.")
        except Exception as e:
            print(f"   -> Failed to send ntfy notification: {e}")

    # --- Send WeChat Work bot notification ---
    if WX_BOT_URL:
        payload = {
            "msgtype": "text",
            "text": {
                "content": f"{notification_title}\n{message}"
            }
        }

        try:
            print(f"   -> Sending WeChat Work notification to: {WX_BOT_URL}")
            headers = { "Content-Type": "application/json" }
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(
                    WX_BOT_URL,
                    json=payload,
                    headers=headers,
                    timeout=10
                )
            )
            response.raise_for_status()
            result = response.json()
            print(f"   -> WeChat Work notification sent successfully. Response: {result}")
        except requests.exceptions.RequestException as e:
            print(f"   -> Failed to send WeChat Work notification: {e}")
        except Exception as e:
            print(f"   -> An unknown error occurred while sending WeChat Work notification: {e}")

@retry_on_failure(retries=5, delay=10)
async def get_ai_analysis(product_data, image_paths=None, prompt_text=""):
    """Sends the complete product JSON data and all images to the AI for analysis (asynchronously)."""
    item_info = product_data.get('item_info', {})
    product_id = item_info.get('item_id', 'N/A')

    print(f"\n   [AI Analysis] Starting analysis for product #{product_id} (with {len(image_paths or [])} images)...")
    print(f"   [AI Analysis] Title: {item_info.get('item_title', 'None')}")

    if not prompt_text:
        print("   [AI Analysis] Error: Prompt text for AI analysis was not provided.")
        return None

    product_details_json = json.dumps(product_data, ensure_ascii=False, indent=2)
    system_prompt = prompt_text

    if AI_DEBUG_MODE:
        print("\n--- [AI DEBUG] ---")
        print("--- PROMPT TEXT (first 500 chars) ---")
        print(prompt_text[:500] + "...")
        print("--- PRODUCT DATA (JSON) ---")
        print(product_details_json)
        print("-------------------\n")

    combined_text_prompt = f"""{system_prompt}

Please analyze the following complete product JSON data based on your expertise and my requirements:

```json
    {product_details_json}
"""
    user_content_list = [{"type": "text", "text": combined_text_prompt}]

    if image_paths:
        for path in image_paths:
            base64_image = encode_image_to_base64(path)
            if base64_image:
                user_content_list.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})

    messages = [{"role": "user", "content": user_content_list}]

    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        response_format={"type": "json_object"}
    )

    ai_response_content = response.choices[0].message.content

    if AI_DEBUG_MODE:
        print("\n--- [AI DEBUG] ---")
        print("--- RAW AI RESPONSE ---")
        print(ai_response_content)
        print("---------------------\n")

    try:
        # --- Added code: Extract JSON from a Markdown code block ---
        # Find the first "{" and the last "}" to capture the complete JSON object
        json_start_index = ai_response_content.find('{')
        json_end_index = ai_response_content.rfind('}')
        
        if json_start_index != -1 and json_end_index != -1:
            clean_json_str = ai_response_content[json_start_index : json_end_index + 1]
            return json.loads(clean_json_str)
        else:
            # If "{" or "}" is not found, the response format is abnormal. Try parsing as is and prepare to catch the error.
            print("---!!! AI RESPONSE WARNING: Could not find JSON object markers '{' and '}' in the response. !!!---")
            return json.loads(ai_response_content) # This line will likely trigger an error again, but keeping for logical completeness
        # --- End of modification ---
        
    except json.JSONDecodeError as e:
        print("---!!! AI RESPONSE PARSING FAILED (JSONDecodeError) !!!---")
        print(f"Raw response from AI:\n---\n{ai_response_content}\n---")
        raise e
        
async def scrape_xianyu(task_config: dict, debug_limit: int = 0):
    """
    【Core Executor】
    Asynchronously scrapes Xianyu product data based on a single task configuration,
    and performs real-time, independent AI analysis and notification for each newly found product.
    """
    keyword = task_config['keyword']
    max_pages = task_config.get('max_pages', 1)
    personal_only = task_config.get('personal_only', False)
    min_price = task_config.get('min_price')
    max_price = task_config.get('max_price')
    ai_prompt_text = task_config.get('ai_prompt_text', '')

    processed_item_count = 0
    stop_scraping = False

    processed_links = set()
    output_filename = os.path.join("jsonl", f"{keyword.replace(' ', '_')}_full_data.jsonl")
    if os.path.exists(output_filename):
        print(f"LOG: Existing file {output_filename} found, loading history for deduplication...")
        try:
            with open(output_filename, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        link = record.get('item_info', {}).get('item_link', '')
                        if link:
                            processed_links.add(get_link_unique_key(link))
                    except json.JSONDecodeError:
                        print(f"   [Warning] A line in the file could not be parsed as JSON, skipped.")
            print(f"LOG: Loading complete, {len(processed_links)} processed items recorded.")
        except IOError as e:
            print(f"   [Warning] An error occurred while reading the history file: {e}")
    else:
        print(f"LOG: Output file {output_filename} does not exist, a new file will be created.")

    async with async_playwright() as p:
        if LOGIN_IS_EDGE:
            browser = await p.chromium.launch(headless=RUN_HEADLESS, channel="msedge")
        else:
            # Inside Docker, use Playwright's built-in chromium; locally, use system's Chrome
            if RUNNING_IN_DOCKER:
                browser = await p.chromium.launch(headless=RUN_HEADLESS)
            else:
                browser = await p.chromium.launch(headless=RUN_HEADLESS, channel="chrome")
        context = await browser.new_context(storage_state=STATE_FILE, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3")
        page = await context.new_page()

        try:
            print("LOG: Step 1 - Navigating directly to the search results page...")
            # Build the correct search URL with the 'q' parameter and URL encode it
            params = {'q': keyword}
            search_url = f"https://www.goofish.com/search?{urlencode(params)}"
            print(f"   -> Target URL: {search_url}")

            # Use expect_response to capture the initial search API data during navigation
            async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=30000) as response_info:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

            initial_response = await response_info.value

            # Wait for key filter elements to load to confirm successful entry to the search results page
            await page.wait_for_selector('text=新发布', timeout=15000)

            # --- Added: Check for verification pop-up ---
            baxia_dialog = page.locator("div.baxia-dialog-mask")
            try:
                # Wait for the pop-up to appear within 2 seconds. If it appears, execute the code block.
                await baxia_dialog.wait_for(state='visible', timeout=2000)
                print("\n==================== CRITICAL BLOCK DETECTED ====================")
                print("Xianyu anti-scraping verification pop-up (baxia-dialog) detected, cannot continue.")
                print("This is usually because operations are too frequent or identified as a bot.")
                print("Suggestions:")
                print("1. Stop the script for a while and try again.")
                print("2. (Recommended) Set RUN_HEADLESS=false in the .env file to run in non-headless mode, which may help bypass detection.")
                print(f"Task '{keyword}' will be aborted here.")
                print("===================================================================")
                await browser.close()
                return processed_item_count
            except PlaywrightTimeoutError:
                # Pop-up did not appear within 2 seconds, this is normal, continue execution
                pass
            # --- End of addition ---

            try:
                await page.click("div[class*='closeIconBg']", timeout=3000)
                print("LOG: Closed ad pop-up.")
            except PlaywrightTimeoutError:
                print("LOG: No ad pop-up detected.")

            final_response = None
            print("\nLOG: Step 2 - Applying filters...")
            await page.click('text=新发布')
            await random_sleep(2, 4)
            async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=20000) as response_info:
                await page.click('text=最新')
                await random_sleep(4, 7)
            final_response = await response_info.value

            if personal_only:
                async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=20000) as response_info:
                    await page.click('text=个人闲置')
                    await random_sleep(4, 6)
                final_response = await response_info.value

            if min_price or max_price:
                price_container = page.locator('div[class*="search-price-input-container"]').first
                if await price_container.is_visible():
                    if min_price:
                        await price_container.get_by_placeholder("¥").first.fill(min_price)
                        await random_sleep(1, 2.5)
                    if max_price:
                        await price_container.get_by_placeholder("¥").nth(1).fill(max_price)
                        await random_sleep(1, 2.5)

                    async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=20000) as response_info:
                        await page.keyboard.press('Tab')
                        await random_sleep(4, 7)
                    final_response = await response_info.value
                else:
                    print("LOG: Warning - Price input container not found.")

            print("\nLOG: All filters have been applied, starting to process the item list...")

            current_response = final_response if final_response and final_response.ok else initial_response
            for page_num in range(1, max_pages + 1):
                if stop_scraping: break
                print(f"\n--- Processing page {page_num}/{max_pages} ---")

                if page_num > 1:
                    next_btn = page.locator("[class*='search-pagination-arrow-right']:not([disabled])")
                    if not await next_btn.count():
                        print("LOG: No available 'Next Page' button found, stopping pagination.")
                        break
                    try:
                        async with page.expect_response(lambda r: API_URL_PATTERN in r.url, timeout=20000) as response_info:
                            await next_btn.click()
                            await random_sleep(5, 8)
                        current_response = await response_info.value
                    except PlaywrightTimeoutError:
                        print(f"LOG: Timed out while turning to page {page_num}.")
                        break

                if not (current_response and current_response.ok):
                    print(f"LOG: Invalid response for page {page_num}, skipping.")
                    continue

                basic_items = await _parse_search_results_json(await current_response.json(), f"Page {page_num}")
                if not basic_items: break

                total_items_on_page = len(basic_items)
                for i, item_data in enumerate(basic_items, 1):
                    if debug_limit > 0 and processed_item_count >= debug_limit:
                        print(f"LOG: Debug limit ({debug_limit}) reached, stopping fetching new items.")
                        stop_scraping = True
                        break

                    unique_key = get_link_unique_key(item_data["item_link"])
                    if unique_key in processed_links:
                        print(f"   -> [Page Progress {i}/{total_items_on_page}] Item '{item_data['item_title'][:20]}...' already exists, skipping.")
                        continue

                    print(f"-> [Page Progress {i}/{total_items_on_page}] New item found, getting details: {item_data['item_title'][:30]}...")
                    await random_sleep(3, 6)

                    detail_page = await context.new_page()
                    try:
                        async with detail_page.expect_response(lambda r: DETAIL_API_URL_PATTERN in r.url, timeout=25000) as detail_info:
                            await detail_page.goto(item_data["item_link"], wait_until="domcontentloaded", timeout=25000)

                        detail_response = await detail_info.value
                        if detail_response.ok:
                            detail_json = await detail_response.json()

                            ret_string = str(await safe_get(detail_json, 'ret', default=[]))
                            if "FAIL_SYS_USER_VALIDATE" in ret_string:
                                print("\n==================== CRITICAL BLOCK DETECTED ====================")
                                print("Xianyu anti-scraping verification (FAIL_SYS_USER_VALIDATE) detected, the program will terminate.")
                                long_sleep_duration = random.randint(300, 600)
                                print(f"To avoid account risk, a long sleep of {long_sleep_duration} seconds will be performed before exiting...")
                                await asyncio.sleep(long_sleep_duration)
                                print("Long sleep finished, exiting safely now.")
                                print("===================================================================")
                                stop_scraping = True
                                break

                            item_do = await safe_get(detail_json, 'data', 'itemDO', default={})
                            seller_do = await safe_get(detail_json, 'data', 'sellerDO', default={})

                            reg_days_raw = await safe_get(seller_do, 'userRegDay', default=0)
                            registration_duration_text = format_registration_days(reg_days_raw)

                            zhima_credit_text = await safe_get(seller_do, 'zhimaLevelInfo', 'levelName')

                            image_infos = await safe_get(item_do, 'imageInfos', default=[])
                            if image_infos:
                                all_image_urls = [img.get('url') for img in image_infos if img.get('url')]
                                if all_image_urls:
                                    item_data['item_image_list'] = all_image_urls
                                    item_data['item_main_image_link'] = all_image_urls[0]

                            item_data['wants_count'] = await safe_get(item_do, 'wantCnt', default=item_data.get('wants_count', 'NaN'))
                            item_data['views_count'] = await safe_get(item_do, 'browseCnt', default='-')

                            user_profile_data = {}
                            user_id = await safe_get(seller_do, 'sellerId')
                            if user_id:
                                user_profile_data = await scrape_user_profile(context, str(user_id))
                            else:
                                print("   [Warning] Could not get seller ID from detail API.")
                            user_profile_data['seller_zhima_credit'] = zhima_credit_text
                            user_profile_data['seller_registration_duration'] = registration_duration_text

                            final_record = {
                                "crawl_time": datetime.now().isoformat(),
                                "search_keyword": keyword,
                                "task_name": task_config.get('task_name', 'Untitled Task'),
                                "item_info": item_data,
                                "seller_info": user_profile_data
                            }

                            print(f"   -> Starting real-time AI analysis for item #{item_data['item_id']}...")
                            image_urls = item_data.get('item_image_list', [])
                            downloaded_image_paths = await download_all_images(item_data['item_id'], image_urls)

                            ai_analysis_result = None
                            if ai_prompt_text:
                                try:
                                    ai_analysis_result = await get_ai_analysis(final_record, downloaded_image_paths, prompt_text=ai_prompt_text)
                                    if ai_analysis_result:
                                        final_record['ai_analysis'] = ai_analysis_result
                                        print(f"   -> AI analysis complete. Recommendation status: {ai_analysis_result.get('is_recommended')}")
                                    else:
                                        final_record['ai_analysis'] = {'error': 'AI analysis returned None after retries.'}
                                except Exception as e:
                                    print(f"   -> A critical error occurred during AI analysis: {e}")
                                    final_record['ai_analysis'] = {'error': str(e)}
                            else:
                                print("   -> AI prompt not configured for this task, skipping analysis.")

                            if ai_analysis_result and ai_analysis_result.get('is_recommended'):
                                print(f"   -> Item recommended by AI, preparing to send notification...")
                                await send_ntfy_notification(item_data, ai_analysis_result.get("reason", "No reason provided"))

                            await save_to_jsonl(final_record, keyword)

                            processed_links.add(unique_key)
                            processed_item_count += 1
                            print(f"   -> Item processing complete. Total processed new items: {processed_item_count}.")

                            print("   [Anti-Scraping] Performing a major random delay to simulate user browsing interval...")
                            await random_sleep(15, 30)
                        else:
                            print(f"   Error: Failed to get item detail API response, status code: {detail_response.status}")
                            if AI_DEBUG_MODE:
                                print(f"--- [DETAIL DEBUG] FAILED RESPONSE from {item_data['item_link']} ---")
                                try:
                                    print(await detail_response.text())
                                except Exception as e:
                                    print(f"Could not read response content: {e}")
                                print("----------------------------------------------------")

                    except PlaywrightTimeoutError:
                        print(f"   Error: Timed out visiting item detail page or waiting for API response.")
                    except Exception as e:
                        print(f"   Error: An unknown error occurred while processing item details: {e}")
                    finally:
                        await detail_page.close()
                        await random_sleep(2, 4)

                if not stop_scraping and page_num < max_pages:
                    print(f"--- Page {page_num} processing complete, preparing for next page. Executing a long delay between pages... ---")
                    await random_sleep(25, 50)

        except PlaywrightTimeoutError as e:
            print(f"\nOperation timed out: A page element or network response did not appear in time.\n{e}")
        except Exception as e:
            print(f"\nAn unknown error occurred during scraping: {e}")
        finally:
            print("\nLOG: Task execution finished, the browser will close in 5 seconds...")
            await asyncio.sleep(5)
            if debug_limit:
                input("Press Enter to close the browser...")
            await browser.close()

    return processed_item_count

async def main():
    parser = argparse.ArgumentParser(
        description="Xianyu item monitoring script with multi-task configuration and real-time AI analysis.",
        epilog="""
Example usage:
  # Run all enabled tasks defined in config.json
  python spider_v2.py

  # Debug mode: Run all tasks, but only process the first 3 newly found items for each task
  python spider_v2.py --debug-limit 3
""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--debug-limit", type=int, default=0, help="Debug mode: each task processes only the first N new items (0 for no limit)")
    parser.add_argument("--config", type=str, default="config.json", help="Specify the task configuration file path (default: config.json)")
    args = parser.parse_.parse_args()

    if not os.path.exists(STATE_FILE):
        sys.exit(f"Error: Login state file '{STATE_FILE}' not found. Please run login.py first to generate it.")

    if not os.path.exists(args.config):
        sys.exit(f"Error: Configuration file '{args.config}' not found.")

    try:
        with open(args.config, 'r', encoding='utf-8') as f:
            tasks_config = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        sys.exit(f"Error: Failed to read or parse configuration file '{args.config}': {e}")

    # Read all prompt file contents
    for task in tasks_config:
        if task.get("enabled", False) and task.get("ai_prompt_base_file") and task.get("ai_prompt_criteria_file"):
            try:
                with open(task["ai_prompt_base_file"], 'r', encoding='utf-8') as f_base:
                    base_prompt = f_base.read()
                with open(task["ai_prompt_criteria_file"], 'r', encoding='utf-8') as f_criteria:
                    criteria_text = f_criteria.read()
                
                # Dynamically combine into the final prompt
                task['ai_prompt_text'] = base_prompt.replace("{{CRITERIA_SECTION}}", criteria_text)

            except FileNotFoundError as e:
                print(f"Warning: Prompt file for task '{task['task_name']}' is missing: {e}. AI analysis for this task will be skipped.")
                task['ai_prompt_text'] = ""
        elif task.get("enabled", False) and task.get("ai_prompt_file"):
            try:
                with open(task["ai_prompt_file"], 'r', encoding='utf-8') as f:
                    task['ai_prompt_text'] = f.read()
            except FileNotFoundError:
                print(f"Warning: Prompt file '{task['ai_prompt_file']}' for task '{task['task_name']}' not found. AI analysis for this task will be skipped.")
                task['ai_prompt_text'] = ""

    print("\n--- Starting Monitoring Tasks ---")
    if args.debug_limit > 0:
        print(f"** Debug mode activated, each task will process a maximum of {args.debug_limit} new items **")
    print("--------------------")

    active_task_configs = [task for task in tasks_config if task.get("enabled", False)]
    if not active_task_configs:
        print("No enabled tasks in the configuration file, exiting.")
        return

    # Create an async execution coroutine for each enabled task
    coroutines = []
    for task_conf in active_task_configs:
        print(f"-> Task '{task_conf['task_name']}' has been added to the execution queue.")
        coroutines.append(scrape_xianyu(task_config=task_conf, debug_limit=args.debug_limit))

    # Concurrently execute all tasks
    results = await asyncio.gather(*coroutines, return_exceptions=True)

    print("\n--- All Tasks Execution Finished ---")
    for i, result in enumerate(results):
        task_name = active_task_configs[i]['task_name']
        if isinstance(result, Exception):
            print(f"Task '{task_name}' was terminated due to an exception: {result}")
        else:
            print(f"Task '{task_name}' finished normally, processed {result} new items in this run.")

if __name__ == "__main__":
    asyncio.run(main())
