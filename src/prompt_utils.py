import asyncio
import json
import os
import sys

import aiofiles

from src.config import MODEL_NAME, client

# The meta-prompt to instruct the AI
META_PROMPT_TEMPLATE = """
你是一位世界级的AI提示词工程大师。你的任务是根据用户提供的【购买需求】，模仿一个【参考范例】，为闲鱼监控机器人的AI分析模块（代号 EagleEye）生成一份全新的【分析标准】文本。

你的输出必须严格遵循【参考范例】的结构、语气和核心原则，但内容要完全针对用户的【购买需求】进行定制。最终生成的文本将作为AI分析模块的思考指南。

---
这是【参考范例】（`macbook_criteria.txt`）：
```text
{reference_text}
```
---

这是用户的【购买需求】：
```text
{user_description}
```
---

请现在开始生成全新的【分析标准】文本。请注意：
1.  **只输出新生成的文本内容**，不要包含任何额外的解释、标题或代码块标记。
2.  保留范例中的 `[V6.3 核心升级]`、`[V6.4 逻辑修正]` 等版本标记，这有助于保持格式一致性。
3.  将范例中所有与 "MacBook" 相关的内容，替换为与用户需求商品相关的内容。
4.  思考并生成针对新商品类型的“一票否决硬性原则”和“危险信号清单”。
"""


async def generate_criteria(user_description: str, reference_file_path: str) -> str:
    """
    Generates a new criteria file content using AI.
    """
    if not client:
        raise RuntimeError("AI客户端未初始化，无法生成分析标准。请检查.env配置。")

    print(f"正在读取参考文件: {reference_file_path}")
    try:
        with open(reference_file_path, 'r', encoding='utf-8') as f:
            reference_text = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"参考文件未找到: {reference_file_path}")
    except IOError as e:
        raise IOError(f"读取参考文件失败: {e}")

    print("正在构建发送给AI的指令...")
    prompt = META_PROMPT_TEMPLATE.format(
        reference_text=reference_text,
        user_description=user_description
    )

    print("正在调用AI生成新的分析标准，请稍候...")
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5, # Lower temperature for more predictable structure
        )
        generated_text = response.choices[0].message.content
        print("AI已成功生成内容。")
        return generated_text.strip()
    except Exception as e:
        # 增强错误日志，显示更多详细信息以便于调试
        error_details = f"调用 OpenAI API 时出错: {type(e).__name__}: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_details += f"\nHTTP状态码: {e.response.status_code}"
            try:
                error_details += f"\n响应内容: {e.response.text}"
            except:
                error_details += "\n无法获取响应内容"
        print(error_details)
        raise e


async def update_config_with_new_task(new_task: dict, config_file: str = "config.json"):
    """
    将一个新任务添加到指定的JSON配置文件中。
    """
    print(f"正在更新配置文件: {config_file}")
    try:
        # 读取现有配置
        config_data = []
        if os.path.exists(config_file):
            async with aiofiles.open(config_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                # 处理空文件的情况
                if content.strip():
                    config_data = json.loads(content)

        # 追加新任务
        config_data.append(new_task)

        # 写回配置文件
        async with aiofiles.open(config_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(config_data, ensure_ascii=False, indent=2))
        
        print(f"成功！新任务 '{new_task.get('task_name')}' 已添加到 {config_file} 并已启用。")
        return True
    except json.JSONDecodeError:
        sys.stderr.write(f"错误: 配置文件 {config_file} 格式错误，无法解析。\n")
        return False
    except IOError as e:
        sys.stderr.write(f"错误: 读写配置文件失败: {e}\n")
        return False
