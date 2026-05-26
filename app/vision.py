"""Vision middleware.

Intercepts image content blocks in incoming requests and converts them to text
descriptions via a configurable OpenAI-compatible vision endpoint. This lets
any text-only model (e.g. DeepSeek-Chat, DeepSeek-Reasoner) handle image inputs.

When VISION_* env vars are not set, this module is a no-op: image blocks are
passed through unchanged (useful when the upstream already supports vision).

Architecture (mirrors web_search two-pass pattern):
  1. Scan all message content blocks for images.
  2. Call vision model in parallel via asyncio.gather for each image.
  3. Replace each image block with a text block: "[Image N] <caption>".
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.schemas import MessageRequest

logger = logging.getLogger(__name__)


def _vision_enabled() -> bool:
    return bool(settings.vision_base_url and settings.vision_api_key and settings.vision_model)


async def _describe_image(
    image_data: str,
    media_type: Optional[str],
    image_url: Optional[str],
    index: int,
) -> str:
    """Call the vision provider and return a text description."""
    base_url = settings.vision_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.vision_api_key}",
        "Content-Type": "application/json",
    }

    if image_url:
        image_content: Dict[str, Any] = {"type": "image_url", "image_url": {"url": image_url}}
    else:
        # base64 data URI
        mtype = media_type or "image/jpeg"
        image_content = {
            "type": "image_url",
            "image_url": {"url": f"data:{mtype};base64,{image_data}"},
        }

    body = {
        "model": settings.vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": settings.vision_prompt},
                    image_content,
                ],
            }
        ],
        "max_tokens": 1024,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"[Vision] image {index} description failed: {e}")
        return f"[Image {index}: description unavailable]"


def _extract_images(messages: List[Any]) -> List[Dict[str, Any]]:
    """Find all image blocks across all messages, recording their location."""
    found = []
    for msg_idx, msg in enumerate(messages):
        content = msg.get("content", []) if isinstance(msg, dict) else []
        if isinstance(content, str):
            continue
        for block_idx, block in enumerate(content):
            b = block if isinstance(block, dict) else (block.model_dump() if hasattr(block, "model_dump") else {})
            if b.get("type") == "image":
                source = b.get("source", {})
                found.append({
                    "msg_idx": msg_idx,
                    "block_idx": block_idx,
                    "data": source.get("data"),
                    "media_type": source.get("media_type"),
                    "url": source.get("url"),
                    "image_index": len(found) + 1,
                })
    return found


async def maybe_apply_vision(request: MessageRequest) -> MessageRequest:
    """Replace image blocks with text descriptions if vision middleware is enabled."""
    if not _vision_enabled():
        return request

    messages_raw = [
        m.model_dump(exclude_none=True) if hasattr(m, "model_dump") else m
        for m in request.messages
    ]

    images = _extract_images(messages_raw)
    if not images:
        return request

    logger.info(f"[Vision] processing {len(images)} image(s) via {settings.vision_model}")

    # Describe all images in parallel
    tasks = [
        _describe_image(
            image_data=img["data"],
            media_type=img["media_type"],
            image_url=img["url"],
            index=img["image_index"],
        )
        for img in images
    ]
    captions = await asyncio.gather(*tasks)

    # Substitute image blocks with text blocks in the raw message list
    for img, caption in zip(images, captions):
        msg = messages_raw[img["msg_idx"]]
        content = msg.get("content", [])
        content[img["block_idx"]] = {
            "type": "text",
            "text": f"[Image {img['image_index']}] {caption}",
        }

    # Rebuild MessageRequest with modified messages
    return MessageRequest(
        model=request.model,
        messages=messages_raw,
        max_tokens=request.max_tokens,
        system=request.system,
        temperature=request.temperature,
        top_p=request.top_p,
        top_k=request.top_k,
        stop_sequences=request.stop_sequences,
        stream=request.stream,
        tools=request.tools,
        tool_choice=request.tool_choice,
        thinking=request.thinking,
        metadata=request.metadata,
        output_config=request.output_config,
        context_management=request.context_management,
    )
