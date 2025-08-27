import json

from pydantic import BaseModel
from typing import Optional

from src.config import CONFIG_FILE
from src.file_operator import FileOperator


class Task(BaseModel):
    task_name: str
    enabled: bool
    keyword: str
    description: str
    max_pages: int
    personal_only: bool
    min_price: Optional[str] = None
    max_price: Optional[str] = None
    cron: Optional[str] = None
    ai_prompt_base_file: str
    ai_prompt_criteria_file: str
    is_running: Optional[bool] = False
    title_include_keywords: Optional[list[str]] = None
    title_exclude_keywords: Optional[list[str]] = None
    title_regex_pattern: Optional[str] = None


class TaskUpdate(BaseModel):
    task_name: Optional[str] = None
    enabled: Optional[bool] = None
    keyword: Optional[str] = None
    description: Optional[str] = None
    max_pages: Optional[int] = None
    personal_only: Optional[bool] = None
    min_price: Optional[str] = None
    max_price: Optional[str] = None
    cron: Optional[str] = None
    ai_prompt_base_file: Optional[str] = None
    ai_prompt_criteria_file: Optional[str] = None
    is_running: Optional[bool] = None
    title_include_keywords: Optional[list[str]] = None
    title_exclude_keywords: Optional[list[str]] = None
    title_regex_pattern: Optional[str] = None


async def add_task(task: Task) -> bool:
    config_file_op = FileOperator(CONFIG_FILE)

    config_data_str = await config_file_op.read()
    config_data = json.loads(config_data_str) if config_data_str else []
    config_data.append(task)

    return await config_file_op.write(json.dumps(config_data, ensure_ascii=False, indent=2))


async def update_task(task_id: int, task: Task) -> bool:
    config_file_op = FileOperator(CONFIG_FILE)

    config_data_str = await config_file_op.read()

    if not config_data_str:
        return False

    config_data = json.loads(config_data_str)

    if len(config_data) <= task_id:
        return False

    config_data[task_id] = task

    return await config_file_op.write(json.dumps(config_data, ensure_ascii=False, indent=2))


async def get_task(task_id: int) -> Task | None:
    config_file_op = FileOperator(CONFIG_FILE)
    config_data_str = await config_file_op.read()

    if not config_data_str:
        return None

    config_data = json.loads(config_data_str)
    if len(config_data) <= task_id:
        return None

    return config_data[task_id]


async def remove_task(task_id: int) -> bool:
    config_file_op = FileOperator(CONFIG_FILE)
    config_data_str = await config_file_op.read()
    if not config_data_str:
        return True

    config_data = json.loads(config_data_str)

    if len(config_data) <= task_id:
        return True

    config_data.pop(task_id)

    return await config_file_op.write(json.dumps(config_data, ensure_ascii=False, indent=2))
