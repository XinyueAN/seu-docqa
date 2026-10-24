from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

import httpx
from PIL import Image

from docqa.config import settings


class ModelNotConfigured(RuntimeError):
    pass


async def _request(messages: list[dict[str, Any]]) -> str:
    if not settings.api_key:
        raise ModelNotConfigured("未找到 DeepSeek API 密钥。请检查项目根目录的密钥文件或配置 DEEPSEEK_API_KEY。")
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
        response = await client.post(
            f"{settings.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.api_key}"},
            json={"model": settings.model, "messages": messages, "stream": False},
        )
        response.raise_for_status()
        body = response.json()
    return body["choices"][0]["message"]["content"]


async def complete(messages: list[dict[str, Any]]) -> str:
    return await _request(messages)


async def describe_image(image_bytes: bytes, hint: str = "") -> str:
    """Describe one document image using DeepSeek Flash vision input."""
    with Image.open(BytesIO(image_bytes)) as source:
        source.thumbnail((1600, 1600))
        image = source.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=84, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    prompt = (
        "你在为本地文档建立可检索的图像文本索引。请按以下格式用中文输出：\n"
        "【可见文字】尽可能逐项转写清晰可辨的标题、标签、图例、关键数值和表格文字；看不清处写[无法辨认]。\n"
        "【图表关系】说明流程方向、节点关系、坐标轴/趋势或表格结构。\n"
        "【要点】概括图片表达的结论。\n"
        "严格区分可见事实与推测，不补造图片中不存在的文字。无需重复文档名和页码。"
    )
    if hint:
        prompt += f"\n文档上下文：{hint[:1000]}"
    return await _request([{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}", "detail": "high"}},
        ],
    }])
