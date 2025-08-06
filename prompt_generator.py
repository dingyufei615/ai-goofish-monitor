import os
import sys
import argparse
import asyncio
import json
import aiofiles
from dotenv import load_dotenv
from openai import AsyncOpenAI

# --- AI Configuration ---
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("OPENAI_BASE_URL")
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")
PROXY_URL = os.getenv("PROXY_URL")

# Check configuration
if not all([BASE_URL, MODEL_NAME]):
    raise ValueError("Error: Please ensure that OPENAI_BASE_URL and OPENAI_MODEL_NAME are fully set in the .env file. (OPENAI_API_KEY is optional for some services)")

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
    raise RuntimeError(f"Error initializing OpenAI client: {e}") from e

# The meta-prompt to instruct the AI
META_PROMPT_TEMPLATE = """
You are a world-class AI prompt engineering master. Your task is to generate a brand new "Analysis Criteria" text for the Xianyu monitoring bot's AI analysis module (codenamed EagleEye), based on the user-provided [Purchase Demand] and imitating a [Reference Example].

Your output must strictly follow the structure, tone, and core principles of the [Reference Example], but the content must be completely customized for the user's [Purchase Demand]. The final generated text will serve as the thinking guide for the AI analysis module.

---
This is the [Reference Example] (`macbook_criteria.txt`):
```text
{reference_text}
```
---

This is the user's [Purchase Demand]:
```text
{user_description}
```
---

Please start generating the new "Analysis Criteria" text now. Note:
1.  **Only output the newly generated text content**, without any additional explanations, titles, or code block markers.
2.  Retain version markers from the example, such as `[V6.3 Core Upgrade]` and `[V6.4 Logic Correction]`, to maintain format consistency.
3.  Replace all content related to "MacBook" in the example with content related to the user's desired product.
4.  Think about and generate "hard deal-breaker rules" and a "red flag list" for the new product type.
"""

async def generate_criteria(user_description: str, reference_file_path: str) -> str:
    """
    Generates a new criteria file content using AI.
    """
    print(f"Reading reference file: {reference_file_path}")
    try:
        with open(reference_file_path, 'r', encoding='utf-8') as f:
            reference_text = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Reference file not found: {reference_file_path}")
    except IOError as e:
        raise IOError(f"Failed to read reference file: {e}")

    print("Constructing the prompt to send to the AI...")
    prompt = META_PROMPT_TEMPLATE.format(
        reference_text=reference_text,
        user_description=user_description
    )

    print("Calling AI to generate new analysis criteria, please wait...")
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5, # Lower temperature for more predictable structure
        )
        generated_text = response.choices[0].message.content
        print("AI has successfully generated the content.")
        return generated_text.strip()
    except Exception as e:
        print(f"An error occurred while calling the OpenAI API: {e}")
        raise e


async def update_config_with_new_task(new_task: dict, config_file: str = "config.json"):
    """
    Adds a new task to the specified JSON configuration file.
    """
    print(f"Updating configuration file: {config_file}")
    try:
        # Read existing configuration
        config_data = []
        if os.path.exists(config_file):
            async with aiofiles.open(config_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                # Handle the case of an empty file
                if content.strip():
                    config_data = json.loads(content)

        # Append the new task
        config_data.append(new_task)

        # Write the configuration back to the file
        async with aiofiles.open(config_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(config_data, ensure_ascii=False, indent=2))
        
        print(f"Success! New task '{new_task.get('task_name')}' has been added to {config_file} and enabled.")
        return True
    except json.JSONDecodeError:
        sys.stderr.write(f"Error: Configuration file {config_file} is malformed and cannot be parsed.\n")
        return False
    except IOError as e:
        sys.stderr.write(f"Error: Failed to read or write configuration file: {e}\n")
        return False


async def main():
    parser = argparse.ArgumentParser(
        description="Uses AI to generate an analysis criteria file for the Xianyu monitoring bot based on user needs and a reference example, and automatically updates config.json.",
        epilog="""
Example usage:
  python prompt_generator.py \\
    --description "I want to buy a Sony A7M4 camera, 95% new or better, with a budget between 10,000 and 13,000 yuan..." \\
    --output prompts/sony_a7m4_criteria.txt \\
    --task-name "Sony A7M4" \\
    --keyword "a7m4" \\
    --min-price "10000" \\
    --max-price "13000"
""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--description", type=str, required=True, help="Your detailed purchase requirement description.")
    parser.add_argument("--output", type=str, required=True, help="The save path for the newly generated analysis criteria file.")
    parser.add_argument("--reference", type=str, default="prompts/macbook_criteria.txt", help="The path to the reference file to be used as a template.")
    # New arguments for config.json
    parser.add_argument("--task-name", type=str, required=True, help="The name of the new task (e.g., 'Sony A7M4').")
    parser.add_argument("--keyword", type=str, required=True, help="The search keyword for the new task (e.g., 'a7m4').")
    parser.add_argument("--min-price", type=str, help="The minimum price.")
    parser.add_argument("--max-price", type=str, help="The maximum price.")
    parser.add_argument("--max-pages", type=int, default=3, help="The maximum number of search pages (default: 3).")
    parser.add_argument('--no-personal-only', dest='personal_only', action='store_false', help="If set, does not filter for personal sellers.")
    parser.set_defaults(personal_only=True)
    parser.add_argument("--config-file", type=str, default="config.json", help="The path to the task configuration file (default: config.json).")
    args = parser.parse_args()

    # Ensure the output directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    generated_criteria = await generate_criteria(args.description, args.reference)

    if generated_criteria:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(generated_criteria)
            print(f"\nSuccess! The new analysis criteria have been saved to: {args.output}")
        except IOError as e:
            sys.exit(f"Error: Failed to write to the output file: {e}")

        # Create the new task entry
        new_task = {
            "task_name": args.task_name,
            "enabled": True,
            "keyword": args.keyword,
            "max_pages": args.max_pages,
            "personal_only": args.personal_only,
            "ai_prompt_base_file": "prompts/base_prompt.txt",
            "ai_prompt_criteria_file": args.output
        }
        if args.min_price:
            new_task["min_price"] = args.min_price
        if args.max_price:
            new_task["max_price"] = args.max_price

        # Update config.json using the refactored function
        success = await update_config_with_new_task(new_task, args.config_file)
        if success:
            print("You can now run `python spider_v2.py` directly to start all monitors, including the new task.")

if __name__ == "__main__":
    asyncio.run(main())
