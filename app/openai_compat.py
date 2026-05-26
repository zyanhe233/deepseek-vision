"""OpenAI Chat Completions compatibility layer.

Exposes POST /v1/chat/completions so any OpenAI-compatible client (LangChain,
OpenAI SDK, Cherry Studio, Cline, etc.) can use this proxy without any
client-side changes.

Request flow:
  OpenAI ChatCompletion request
    → convert to Anthropic MessageRequest
    → vision middleware (same as /v1/messages path)
    → backend.invoke / backend.stream
    → convert response back to OpenAI ChatCompletion format
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.auth import require_auth_flexible
from app.router import select_backend
from app.schemas import MessageRequest

logger = logging.getLogger(__name__)

router = APIRouter()


# --- OpenAI request/response models ---

class _OAIContentPart(BaseModel):
    type: str
    text: Optional[str] = None
    image_url: Optional[Dict[str, str]] = None


class _OAIMessage(BaseModel):
    role: str
    content: Union[str, List[_OAIContentPart], None] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class _OAITool(BaseModel):
    type: str = "function"
    function: Dict[str, Any]


class _OAIChatRequest(BaseModel):
    model: str
    messages: List[_OAIMessage]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    tools: Optional[List[_OAITool]] = None
    tool_choice: Optional[Any] = None
    # Unsupported fields are accepted but silently ignored
    n: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Dict[str, float]] = None
    user: Optional[str] = None
    response_format: Optional[Dict[str, Any]] = None


# --- Converters: OpenAI → Anthropic ---

def _convert_content(content: Union[str, List[_OAIContentPart], None]) -> List[Dict[str, Any]]:
    """Convert OpenAI message content to Anthropic content block list."""
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    blocks: List[Dict[str, Any]] = []
    for part in content:
        if part.type == "text":
            blocks.append({"type": "text", "text": part.text or ""})
        elif part.type == "image_url" and part.image_url:
            url = part.image_url.get("url", "")
            if url.startswith("data:"):
                # data:<media_type>;base64,<data>
                try:
                    header, b64data = url.split(",", 1)
                    media_type = header.split(";")[0].replace("data:", "")
                    blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64data},
                    })
                except Exception:
                    blocks.append({"type": "text", "text": f"[image: {url[:80]}]"})
            else:
                blocks.append({
                    "type": "image",
                    "source": {"type": "url", "url": url},
                })
    return blocks


def _oai_messages_to_anthropic(
    messages: List[_OAIMessage],
) -> tuple[Optional[List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """Split OpenAI messages into (system_blocks, anthropic_messages)."""
    system_blocks: List[Dict[str, Any]] = []
    anthropic_messages: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.role

        if role == "system":
            text = msg.content if isinstance(msg.content, str) else (
                " ".join(p.text or "" for p in msg.content if p.type == "text")
                if isinstance(msg.content, list) else ""
            )
            system_blocks.append({"type": "text", "text": text})
            continue

        if role == "tool":
            # OpenAI tool result → Anthropic tool_result
            anthropic_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content if isinstance(msg.content, str) else "",
                }],
            })
            continue

        if role == "assistant":
            content_blocks: List[Dict[str, Any]] = []
            if msg.content:
                content_blocks.extend(_convert_content(msg.content))
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"toolu_{uuid4().hex[:16]}"),
                        "name": fn.get("name", ""),
                        "input": args,
                    })
            anthropic_messages.append({"role": "assistant", "content": content_blocks})
            continue

        # user
        anthropic_messages.append({
            "role": "user",
            "content": _convert_content(msg.content),
        })

    return system_blocks or None, anthropic_messages


def _oai_tools_to_anthropic(tools: Optional[List[_OAITool]]) -> Optional[List[Dict[str, Any]]]:
    if not tools:
        return None
    result = []
    for tool in tools:
        fn = tool.function
        result.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def _oai_tool_choice_to_anthropic(tool_choice: Any) -> Optional[Any]:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        if tool_choice == "none":
            return None
        if tool_choice in ("auto", "required"):
            return "auto"
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        name = (tool_choice.get("function") or {}).get("name")
        if name:
            return {"type": "tool", "name": name}
    return "auto"


def _build_message_request(oai: _OAIChatRequest) -> MessageRequest:
    system_blocks, messages = _oai_messages_to_anthropic(oai.messages)
    stop_sequences = None
    if oai.stop:
        stop_sequences = [oai.stop] if isinstance(oai.stop, str) else oai.stop

    return MessageRequest(
        model=oai.model,
        messages=messages,
        max_tokens=oai.max_tokens or 4096,
        system=system_blocks,
        temperature=oai.temperature,
        top_p=oai.top_p,
        stop_sequences=stop_sequences,
        stream=oai.stream,
        tools=_oai_tools_to_anthropic(oai.tools),
        tool_choice=_oai_tool_choice_to_anthropic(oai.tool_choice),
    )


# --- Converters: Anthropic → OpenAI ---

_STOP_REASON_MAP = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
}


def _content_to_oai(content: List[Any]) -> tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
    """Convert Anthropic content blocks to (text, tool_calls)."""
    text_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []

    for block in content:
        b = block if isinstance(block, dict) else (block.model_dump() if hasattr(block, "model_dump") else {})
        bt = b.get("type")
        if bt == "text":
            text_parts.append(b.get("text", ""))
        elif bt in ("thinking", "redacted_thinking"):
            pass  # skip reasoning blocks in OpenAI compat output
        elif bt == "tool_use":
            tool_calls.append({
                "id": b.get("id", f"call_{uuid4().hex[:16]}"),
                "type": "function",
                "function": {
                    "name": b.get("name", ""),
                    "arguments": json.dumps(b.get("input", {})),
                },
            })

    text = "\n".join(text_parts) or None
    return text, tool_calls or None


def _anthropic_response_to_oai(response: Any, request_id: str) -> Dict[str, Any]:
    text, tool_calls = _content_to_oai(response.content or [])
    finish_reason = _STOP_REASON_MAP.get(response.stop_reason or "", "stop")

    message: Dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": response.model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        },
    }


# --- Streaming conversion ---

async def _stream_anthropic_to_oai(
    gen: AsyncGenerator[str, None],
    request_id: str,
    model: str,
) -> AsyncGenerator[str, None]:
    """Re-emit Anthropic SSE stream as OpenAI delta SSE stream."""
    chat_id = f"chatcmpl-{request_id}"

    async for chunk in gen:
        for line in chunk.split("\n"):
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue

            otype = obj.get("type")

            if otype == "message_start":
                delta = {"role": "assistant", "content": ""}
                oai_chunk = {
                    "id": chat_id, "object": "chat.completion.chunk",
                    "created": int(time.time()), "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
                yield f"data: {json.dumps(oai_chunk)}\n\n"

            elif otype == "content_block_delta":
                delta_obj = obj.get("delta", {})
                if delta_obj.get("type") == "text_delta":
                    delta = {"content": delta_obj.get("text", "")}
                    oai_chunk = {
                        "id": chat_id, "object": "chat.completion.chunk",
                        "created": int(time.time()), "model": model,
                        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(oai_chunk)}\n\n"

            elif otype == "message_delta":
                stop_reason = _STOP_REASON_MAP.get(
                    (obj.get("delta") or {}).get("stop_reason") or "", "stop"
                )
                oai_chunk = {
                    "id": chat_id, "object": "chat.completion.chunk",
                    "created": int(time.time()), "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": stop_reason}],
                }
                yield f"data: {json.dumps(oai_chunk)}\n\n"

            elif otype == "message_stop":
                yield "data: [DONE]\n\n"

            elif otype == "error":
                err = obj.get("error", {})
                oai_err = {
                    "error": {
                        "message": err.get("message", "upstream error"),
                        "type": err.get("type", "api_error"),
                        "code": None,
                    }
                }
                yield f"data: {json.dumps(oai_err)}\n\n"
                yield "data: [DONE]\n\n"

            # ping / content_block_start / content_block_stop → skip


# --- Endpoint ---

@router.post("/chat/completions")
async def chat_completions(
    oai_request: _OAIChatRequest,
    request: Request,
    api_key: str = Depends(require_auth_flexible),
):
    request_id = uuid4().hex[:24]
    is_stream = oai_request.stream or False

    try:
        msg_request = _build_message_request(oai_request)
        backend = select_backend(msg_request.model)

        # Apply vision middleware
        from app.vision import maybe_apply_vision
        msg_request = await maybe_apply_vision(msg_request)

        if is_stream:
            gen = backend.stream(msg_request, request_id)
            return StreamingResponse(
                _stream_anthropic_to_oai(gen, request_id, oai_request.model),
                media_type="text/event-stream",
            )

        response = await backend.invoke(msg_request, request_id)
        return JSONResponse(content=_anthropic_response_to_oai(response, request_id))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[OAI] error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"type": "api_error", "message": str(e)},
        )
