import uvicorn
import json
import aiofiles
import os
import glob
import asyncio
import signal
import sys
from dotenv import dotenv_values
from fastapi import FastAPI, Request, HTTPException
from prompt_generator import generate_criteria, update_config_with_new_task
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional


class Task(BaseModel):
    task_name: str
    enabled: bool
    keyword: str
    max_pages: int
    personal_only: bool
    min_price: Optional[str] = None
    max_price: Optional[str] = None
    ai_prompt_base_file: str
    ai_prompt_criteria_file: str


class TaskUpdate(BaseModel):
    task_name: Optional[str] = None
    enabled: Optional[bool] = None
    keyword: Optional[str] = None
    max_pages: Optional[int] = None
    personal_only: Optional[bool] = None
    min_price: Optional[str] = None
    max_price: Optional[str] = None
    ai_prompt_base_file: Optional[str] = None
    ai_prompt_criteria_file: Optional[str] = None


class TaskGenerateRequest(BaseModel):
    task_name: str
    keyword: str
    description: str
    personal_only: bool = True
    min_price: Optional[str] = None
    max_price: Optional[str] = None


class PromptUpdate(BaseModel):
    content: str


app = FastAPI(title="Xianyu Intelligent Monitoring Bot")

# --- Globals for process management ---
scraper_process = None

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    Serves the main page of the Web UI.
    """
    return templates.TemplateResponse("index.html", {"request": request})

# --- API Endpoints ---

CONFIG_FILE = "config.json"

@app.get("/api/tasks")
async def get_tasks():
    """
    Reads and returns all tasks from config.json.
    """
    try:
        async with aiofiles.open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            content = await f.read()
            tasks = json.loads(content)
            # Add a unique id to each task
            for i, task in enumerate(tasks):
                task['id'] = i
            return tasks
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Configuration file {CONFIG_FILE} not found.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Configuration file {CONFIG_FILE} is malformed.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while reading the task configuration: {e}")


@app.post("/api/tasks/generate", response_model=dict)
async def generate_task(req: TaskGenerateRequest):
    """
    Generates a new analysis criteria file using AI and creates a new task based on it.
    """
    print(f"Received AI task generation request: {req.task_name}")
    
    # 1. Generate a unique filename for the new criteria file
    safe_keyword = "".join(c for c in req.keyword.lower().replace(' ', '_') if c.isalnum() or c in "_-").rstrip()
    output_filename = f"prompts/{safe_keyword}_criteria.txt"
    
    # 2. Call AI to generate analysis criteria
    try:
        generated_criteria = await generate_criteria(
            user_description=req.description,
            reference_file_path="prompts/macbook_criteria.txt" # Use the default macbook criteria as a reference
        )
        if not generated_criteria:
            raise HTTPException(status_code=500, detail="AI failed to generate analysis criteria.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while calling the AI for criteria generation: {e}")

    # 3. Save the generated text to a new file
    try:
        os.makedirs("prompts", exist_ok=True)
        async with aiofiles.open(output_filename, 'w', encoding='utf-8') as f:
            await f.write(generated_criteria)
        print(f"New analysis criteria saved to: {output_filename}")
    except IOError as e:
        raise HTTPException(status_code=500, detail=f"Failed to save the analysis criteria file: {e}")

    # 4. Create the new task object
    new_task = {
        "task_name": req.task_name,
        "enabled": True,
        "keyword": req.keyword,
        "max_pages": 3, # Default value
        "personal_only": req.personal_only,
        "min_price": req.min_price,
        "max_price": req.max_price,
        "ai_prompt_base_file": "prompts/base_prompt.txt",
        "ai_prompt_criteria_file": output_filename
    }

    # 5. Add the new task to config.json
    success = await update_config_with_new_task(new_task, CONFIG_FILE)
    if not success:
        # If the update fails, it's best to delete the file just created to maintain consistency
        if os.path.exists(output_filename):
            os.remove(output_filename)
        raise HTTPException(status_code=500, detail="Failed to update configuration file config.json.")

    # 6. Return the successfully created task (including ID)
    async with aiofiles.open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        tasks = json.loads(await f.read())
    new_task_with_id = new_task.copy()
    new_task_with_id['id'] = len(tasks) - 1

    return {"message": "AI task created successfully.", "task": new_task_with_id}


@app.post("/api/tasks", response_model=dict)
async def create_task(task: Task):
    """
    Creates a new task and adds it to config.json.
    """
    try:
        async with aiofiles.open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            tasks = json.loads(await f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        tasks = []

    new_task_data = task.dict()
    tasks.append(new_task_data)

    try:
        async with aiofiles.open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(tasks, ensure_ascii=False, indent=2))
        
        new_task_data['id'] = len(tasks) - 1
        return {"message": "Task created successfully.", "task": new_task_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while writing to the configuration file: {e}")


@app.patch("/api/tasks/{task_id}", response_model=dict)
async def update_task(task_id: int, task_update: TaskUpdate):
    """
    Updates the properties of a task with the specified ID.
    """
    try:
        async with aiofiles.open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            tasks = json.loads(await f.read())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read or parse the configuration file: {e}")

    if not (0 <= task_id < len(tasks)):
        raise HTTPException(status_code=404, detail="Task not found.")

    # Update data
    task_changed = False
    update_data = task_update.dict(exclude_unset=True)
    
    if update_data:
        original_task = tasks[task_id].copy()
        tasks[task_id].update(update_data)
        if tasks[task_id] != original_task:
            task_changed = True

    if not task_changed:
        return JSONResponse(content={"message": "No changes in data, update not performed."}, status_code=200)

    # Write back to the file asynchronously
    try:
        async with aiofiles.open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(tasks, ensure_ascii=False, indent=2))
        
        updated_task = tasks[task_id]
        updated_task['id'] = task_id
        return {"message": "Task updated successfully.", "task": updated_task}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while writing to the configuration file: {e}")


@app.post("/api/tasks/start-all", response_model=dict)
async def start_all_tasks():
    """
    Starts all enabled tasks in config.json.
    """
    global scraper_process
    if scraper_process and scraper_process.returncode is None:
        raise HTTPException(status_code=400, detail="Monitoring task is already running.")

    try:
        # Set up log directory and file
        os.makedirs("logs", exist_ok=True)
        log_file_path = os.path.join("logs", "scraper.log")
        
        # Open the log file in append mode, creating it if it doesn't exist.
        # The child process will inherit this file handle.
        log_file_handle = open(log_file_path, 'a', encoding='utf-8')

        # Use the same Python interpreter as the web server to run the scraper script
        # Add the -u flag to disable I/O buffering, ensuring logs are written in real-time
        # On non-Windows systems, use setsid to create a new process group to be able to terminate the whole process tree
        preexec_fn = os.setsid if sys.platform != "win32" else None
        scraper_process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "spider_v2.py",
            stdout=log_file_handle,
            stderr=log_file_handle,
            preexec_fn=preexec_fn
        )
        print(f"Started scraper process with PID: {scraper_process.pid}, logging to {log_file_path}")
        return {"message": "All enabled tasks have been started."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while starting the scraper process: {e}")


@app.post("/api/tasks/stop-all", response_model=dict)
async def stop_all_tasks():
    """
    Stops the currently running monitoring task.
    """
    global scraper_process
    if not scraper_process or scraper_process.returncode is not None:
        raise HTTPException(status_code=400, detail="No monitoring task is currently running.")

    try:
        if sys.platform != "win32":
            # On non-Windows systems, terminate the entire process group
            os.killpg(os.getpgid(scraper_process.pid), signal.SIGTERM)
        else:
            # On Windows, can only terminate the main process
            scraper_process.terminate()

        await scraper_process.wait()
        print(f"Scraper process {scraper_process.pid} has been terminated.")
        scraper_process = None
        return {"message": "All tasks have been stopped."}
    except ProcessLookupError:
        # The process might already be gone
        print(f"The scraper process to be terminated no longer exists.")
        scraper_process = None
        return {"message": "Tasks have already been stopped."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while stopping the scraper process: {e}")


@app.get("/api/logs")
async def get_logs(from_pos: int = 0):
    """
    Gets the content of the scraper log file. Supports incremental reading from a specified position.
    """
    log_file_path = os.path.join("logs", "scraper.log")
    if not os.path.exists(log_file_path):
        return JSONResponse(content={"new_content": "Log file does not exist or has not been created yet.", "new_pos": 0})

    try:
        # Open in binary mode to get file size and position accurately
        async with aiofiles.open(log_file_path, 'rb') as f:
            await f.seek(0, os.SEEK_END)
            file_size = await f.tell()

            # If the client's position is already up-to-date, return immediately
            if from_pos >= file_size:
                return {"new_content": "", "new_pos": file_size}

            await f.seek(from_pos)
            new_bytes = await f.read()
        
        # Decode the fetched bytes
        try:
            new_content = new_bytes.decode('utf-8')
        except UnicodeDecodeError:
            # If utf-8 fails, try reading with gbk and ignore undecodable characters
            new_content = new_bytes.decode('gbk', errors='ignore')

        return {"new_content": new_content, "new_pos": file_size}

    except Exception as e:
        # Return an error message while keeping the position unchanged for the next retry
        return JSONResponse(
            status_code=500,
            content={"new_content": f"\nAn error occurred while reading the log file: {e}", "new_pos": from_pos}
        )


@app.delete("/api/logs", response_model=dict)
async def clear_logs():
    """
    Clears the content of the log file.
    """
    log_file_path = os.path.join("logs", "scraper.log")
    if not os.path.exists(log_file_path):
        return {"message": "Log file does not exist, no need to clear."}

    try:
        # Opening the file in 'w' mode will clear its content
        async with aiofiles.open(log_file_path, 'w') as f:
            await f.write("")
        return {"message": "Logs have been successfully cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while clearing the log file: {e}")


@app.delete("/api/tasks/{task_id}", response_model=dict)
async def delete_task(task_id: int):
    """
    Deletes a task with the specified ID from config.json.
    """
    try:
        async with aiofiles.open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            tasks = json.loads(await f.read())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read or parse the configuration file: {e}")

    if not (0 <= task_id < len(tasks)):
        raise HTTPException(status_code=404, detail="Task not found.")

    deleted_task = tasks.pop(task_id)

    # Try to delete the associated criteria file
    criteria_file = deleted_task.get("ai_prompt_criteria_file")
    if criteria_file and os.path.exists(criteria_file):
        try:
            os.remove(criteria_file)
            print(f"Successfully deleted associated analysis criteria file: {criteria_file}")
        except OSError as e:
            # If file deletion fails, just log it and don't interrupt the main flow
            print(f"Warning: Failed to delete file {criteria_file}: {e}")

    try:
        async with aiofiles.open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(tasks, ensure_ascii=False, indent=2))
        
        return {"message": "Task deleted successfully.", "task_name": deleted_task.get("task_name")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while writing to the configuration file: {e}")


@app.get("/api/results/files")
async def list_result_files():
    """
    Lists all generated .jsonl result files.
    """
    jsonl_dir = "jsonl"
    if not os.path.isdir(jsonl_dir):
        return {"files": []}
    files = [f for f in os.listdir(jsonl_dir) if f.endswith(".jsonl")]
    return {"files": files}


@app.get("/api/results/{filename}")
async def get_result_file_content(filename: str, page: int = 1, limit: int = 20, recommended_only: bool = False, sort_by: str = "crawl_time", sort_order: str = "desc"):
    """
    Reads the content of the specified .jsonl file, with support for pagination, filtering, and sorting.
    """
    if not filename.endswith(".jsonl") or "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    
    filepath = os.path.join("jsonl", filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Result file not found.")

    results = []
    try:
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            async for line in f:
                try:
                    record = json.loads(line)
                    if recommended_only:
                        if record.get("ai_analysis", {}).get("is_recommended") is True:
                            results.append(record)
                    else:
                        results.append(record)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while reading the result file: {e}")

    # --- Sorting logic ---
    def get_sort_key(item):
        info = item.get("item_info", {})
        if sort_by == "publish_time":
            # Handles "Unknown Time" by placing it at the end/start depending on order
            return info.get("publish_time", "0000-00-00 00:00")
        elif sort_by == "price":
            price_str = str(info.get("current_price", "0")).replace("¥", "").replace(",", "").strip()
            try:
                return float(price_str)
            except (ValueError, TypeError):
                return 0.0 # Default for unparsable prices
        else: # default to crawl_time
            return item.get("crawl_time", "")

    is_reverse = (sort_order == "desc")
    results.sort(key=get_sort_key, reverse=is_reverse)
    
    total_items = len(results)
    start = (page - 1) * limit
    end = start + limit
    paginated_results = results[start:end]

    return {
        "total_items": total_items,
        "page": page,
        "limit": limit,
        "items": paginated_results
    }


@app.get("/api/settings/status")
async def get_system_status():
    """
    Checks the status of key system files and configurations.
    """
    global scraper_process
    env_config = dotenv_values(".env")

    # Check if the process is still running
    is_running = False
    if scraper_process:
        if scraper_process.returncode is None:
            is_running = True
        else:
            # Process has finished, reset
            print(f"Detected that scraper process {scraper_process.pid} has finished with return code: {scraper_process.returncode}.")
            scraper_process = None
    
    status = {
        "scraper_running": is_running,
        "login_state_file": {
            "exists": os.path.exists("xianyu_state.json"),
            "path": "xianyu_state.json"
        },
        "env_file": {
            "exists": os.path.exists(".env"),
            "openai_api_key_set": bool(env_config.get("OPENAI_API_KEY")),
            "openai_base_url_set": bool(env_config.get("OPENAI_BASE_URL")),
            "openai_model_name_set": bool(env_config.get("OPENAI_MODEL_NAME")),
            "ntfy_topic_url_set": bool(env_config.get("NTFY_TOPIC_URL")),
        }
    }
    return status


PROMPTS_DIR = "prompts"

@app.get("/api/prompts")
async def list_prompts():
    """
    Lists all .txt files in the prompts/ directory.
    """
    if not os.path.isdir(PROMPTS_DIR):
        return []
    return [f for f in os.listdir(PROMPTS_DIR) if f.endswith(".txt")]


@app.get("/api/prompts/{filename}")
async def get_prompt_content(filename: str):
    """
    Gets the content of a specified prompt file.
    """
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    
    filepath = os.path.join(PROMPTS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Prompt file not found.")
    
    async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
        content = await f.read()
    return {"filename": filename, "content": content}


@app.put("/api/prompts/{filename}")
async def update_prompt_content(filename: str, prompt_update: PromptUpdate):
    """
    Updates the content of a specified prompt file.
    """
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    filepath = os.path.join(PROMPTS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Prompt file not found.")

    try:
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(prompt_update.content)
        return {"message": f"Prompt file '{filename}' updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while writing to the Prompt file: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """
    Ensures all child processes are terminated when the application exits.
    """
    global scraper_process
    if scraper_process and scraper_process.returncode is None:
        print(f"Web server is shutting down, terminating scraper process {scraper_process.pid}...")
        try:
            if sys.platform != "win32":
                os.killpg(os.getpgid(scraper_process.pid), signal.SIGTERM)
            else:
                scraper_process.terminate()

            await asyncio.wait_for(scraper_process.wait(), timeout=5.0)
            print("Scraper process terminated successfully.")
        except ProcessLookupError:
            print("The scraper process to be terminated no longer exists.")
        except asyncio.TimeoutError:
            print("Timed out waiting for scraper process to terminate, forcing termination.")
            try:
                if sys.platform != "win32":
                    os.killpg(os.getpgid(scraper_process.pid), signal.SIGKILL)
                else:
                    scraper_process.kill()
            except ProcessLookupError:
                print("The scraper process to be force-terminated no longer exists.")
        finally:
            scraper_process = None


if __name__ == "__main__":
    # Load environment variables from .env file
    config = dotenv_values(".env")
    
    # Get the server port, defaulting to 8000 if not set
    server_port = int(config.get("SERVER_PORT", 8000))

    # Set default encoding
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    print(f"Starting Web Management UI, please visit http://127.0.0.1:{server_port} in your browser")

    # Start the Uvicorn server
    uvicorn.run(app, host="0.0.0.0", port=server_port)
