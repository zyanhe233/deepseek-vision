"""POST /v1/messages — main Anthropic API endpoint."""
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.auth import require_auth
from app.config import settings
from app.router import select_backend
from app.schemas import MessageRequest, CountTokensRequest, CountTokensResponse
from app import slow_log

logger = logging.getLogger(__name__)

router = APIRouter()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "-"


_ANSI_RESET = "\033[0m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_RED = "\033[31m"


def _colored_ttft(ms: int) -> str:
    if ms < 5000:
        color = _ANSI_GREEN
    elif ms < 10000:
        color = _ANSI_YELLOW
    else:
        color = _ANSI_RED
    return f"{color}ttft={ms}ms{_ANSI_RESET}"


def _log_req(
    *,
    request_id: str,
    ip: str,
    model: str,
    stream: bool,
    status: str,
    duration_ms: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_write: int = 0,
    cache_read: int = 0,
    server_tool: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    req_size_bytes: Optional[int] = None,
    ttft_ms: Optional[int] = None,
) -> None:
    parts = [
        f"id={request_id}",
        f"ip={ip}",
        f"model={model}",
        f"stream={'t' if stream else 'f'}",
        f"status={status}",
        f"dur={duration_ms}ms",
    ]
    if ttft_ms is not None:
        parts.append(_colored_ttft(ttft_ms))
    parts.extend([
        f"in={input_tokens}",
        f"out={output_tokens}",
        f"cache_w={cache_write}",
        f"cache_r={cache_read}",
    ])
    if req_size_bytes is not None:
        parts.append(f"req_size={req_size_bytes}")
    if server_tool:
        ws = server_tool.get("web_search_requests") or 0
        wf = server_tool.get("web_fetch_requests") or 0
        if ws:
            parts.append(f"search={ws}")
        if wf:
            parts.append(f"fetch={wf}")
    if error:
        parts.append(f"err={error[:200]}")
    logger.info("[REQ] " + " ".join(parts))


def _maybe_dump_slow(
    meta: Optional[Dict[str, Any]],
    *,
    request_id: str,
    stream: bool,
    duration_ms: int,
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cache_write: int,
) -> None:
    if not slow_log.should_dump(duration_ms):
        return
    response_body: Any = (meta or {}).get("response_body")
    slow_log.dump(
        request_id=request_id,
        model_id=(meta or {}).get("model_id", "-"),
        stream=stream,
        duration_ms=duration_ms,
        request_size_bytes=(meta or {}).get("request_size_bytes"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        response_body=response_body,
    )


def _extract_sse_data(chunk: str) -> Optional[Dict[str, Any]]:
    for line in chunk.split("\n"):
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except Exception:
                return None
    return None


async def _logged_stream(
    gen: AsyncGenerator[str, None],
    *,
    request_id: str,
    ip: str,
    model: str,
    start: float,
    meta: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[str, None]:
    input_tokens = 0
    output_tokens = 0
    cache_write = 0
    cache_read = 0
    server_tool: Optional[Dict[str, Any]] = None
    status = "success"
    error: Optional[str] = None
    ttft_ms: Optional[int] = None

    try:
        async for chunk in gen:
            if ttft_ms is None and "content_block_delta" in chunk:
                ttft_ms = int((time.monotonic() - start) * 1000)
            try:
                if "message_start" in chunk:
                    obj = _extract_sse_data(chunk)
                    if obj and obj.get("type") == "message_start":
                        usage = (obj.get("message") or {}).get("usage") or {}
                        input_tokens = usage.get("input_tokens", input_tokens) or input_tokens
                        cache_write = usage.get("cache_creation_input_tokens") or cache_write
                        cache_read = usage.get("cache_read_input_tokens") or cache_read
                elif "message_delta" in chunk:
                    obj = _extract_sse_data(chunk)
                    if obj and obj.get("type") == "message_delta":
                        usage = obj.get("usage") or {}
                        output_tokens = usage.get("output_tokens", output_tokens) or output_tokens
                        if usage.get("cache_creation_input_tokens"):
                            cache_write = usage["cache_creation_input_tokens"]
                        if usage.get("cache_read_input_tokens"):
                            cache_read = usage["cache_read_input_tokens"]
                        if usage.get("server_tool_use"):
                            server_tool = usage["server_tool_use"]
                elif '"type": "error"' in chunk or '"type":"error"' in chunk:
                    status = "error"
                    obj = _extract_sse_data(chunk)
                    if obj:
                        err = obj.get("error") or {}
                        error = f"{err.get('type', 'error')}: {err.get('message', '')}"
            except Exception:
                pass
            yield chunk
    except Exception as e:
        status = "error"
        error = f"{type(e).__name__}: {e}"
        raise
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_req(
            request_id=request_id,
            ip=ip,
            model=model,
            stream=True,
            status=status,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write=cache_write,
            cache_read=cache_read,
            server_tool=server_tool,
            error=error,
            req_size_bytes=(meta or {}).get("request_size_bytes"),
            ttft_ms=ttft_ms,
        )
        _maybe_dump_slow(
            meta,
            request_id=request_id,
            stream=True,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read=cache_read,
            cache_write=cache_write,
        )


def _has_tool_type(request: MessageRequest, type_prefixes: set) -> bool:
    if not request.tools:
        return False
    for tool in request.tools:
        t = tool if isinstance(tool, dict) else (tool.model_dump() if hasattr(tool, "model_dump") else {})
        if t.get("type", "") in type_prefixes:
            return True
    return False


@router.post("/messages")
async def create_message(
    request_data: MessageRequest,
    request: Request,
    api_key: str = Depends(require_auth),
    anthropic_beta: Optional[str] = Header(None, alias="anthropic-beta"),
):
    request_id = f"msg_{uuid4().hex[:24]}"
    is_stream = request_data.stream or False
    ip = _client_ip(request)
    model = request_data.model
    start = time.monotonic()

    web_search_types = {"web_search_20250305", "web_search_20260209"}
    web_fetch_types = {"web_fetch_20250910", "web_fetch_20260209"}
    is_web_search = _has_tool_type(request_data, web_search_types)
    is_web_fetch = _has_tool_type(request_data, web_fetch_types)

    try:
        backend = select_backend(model)
        meta: Dict[str, Any] = {}

        # Apply vision middleware before dispatching to the backend.
        from app.vision import maybe_apply_vision
        request_data = await maybe_apply_vision(request_data)

        if is_web_search:
            from app.web_search import handle_web_search, stream_web_search
            if is_stream:
                gen = stream_web_search(request_data, request_id, anthropic_beta, backend)
                return StreamingResponse(
                    _logged_stream(gen, request_id=request_id, ip=ip, model=model, start=start),
                    media_type="text/event-stream",
                )
            response = await handle_web_search(request_data, request_id, anthropic_beta, backend)

        elif is_web_fetch:
            from app.web_fetch import handle_web_fetch, stream_web_fetch
            if is_stream:
                gen = stream_web_fetch(request_data, request_id, anthropic_beta, backend)
                return StreamingResponse(
                    _logged_stream(gen, request_id=request_id, ip=ip, model=model, start=start),
                    media_type="text/event-stream",
                )
            response = await handle_web_fetch(request_data, request_id, anthropic_beta, backend)

        else:
            if is_stream:
                gen = backend.stream(request_data, request_id, anthropic_beta, meta=meta)
                return StreamingResponse(
                    _logged_stream(gen, request_id=request_id, ip=ip, model=model, start=start, meta=meta),
                    media_type="text/event-stream",
                )
            response = await backend.invoke(request_data, request_id, anthropic_beta, meta=meta)

        usage = response.usage
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_req(
            request_id=request_id,
            ip=ip,
            model=model,
            stream=False,
            status="success",
            duration_ms=duration_ms,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_write=usage.cache_creation_input_tokens or 0,
            cache_read=usage.cache_read_input_tokens or 0,
            server_tool=usage.server_tool_use,
            req_size_bytes=meta.get("request_size_bytes"),
        )
        _maybe_dump_slow(
            meta,
            request_id=request_id,
            stream=False,
            duration_ms=duration_ms,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read=usage.cache_read_input_tokens or 0,
            cache_write=usage.cache_creation_input_tokens or 0,
        )
        return JSONResponse(content=response.model_dump(exclude_none=True))

    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        err_msg = f"{detail.get('type', 'http_error')}: {detail.get('message', '')}"
        _log_req(
            request_id=request_id, ip=ip, model=model, stream=is_stream,
            status=f"error_{exc.status_code}",
            duration_ms=int((time.monotonic() - start) * 1000),
            error=err_msg,
        )
        raise
    except Exception as e:
        logger.error(f"Unexpected error in create_message: {e}", exc_info=True)
        _log_req(
            request_id=request_id, ip=ip, model=model, stream=is_stream,
            status="error_500",
            duration_ms=int((time.monotonic() - start) * 1000),
            error=f"{type(e).__name__}: {e}",
        )
        raise HTTPException(
            status_code=500,
            detail={"type": "api_error", "message": f"Internal error: {str(e)}"},
        )


@router.post("/messages/count_tokens", response_model=CountTokensResponse)
async def count_tokens_endpoint(
    request_data: CountTokensRequest,
    request: Request,
    api_key: str = Depends(require_auth),
):
    ip = _client_ip(request)
    start = time.monotonic()
    try:
        backend = select_backend(request_data.model)
        token_count = await backend.count_tokens(request_data)
        logger.info(
            f"[REQ] id=count ip={ip} model={request_data.model} "
            f"op=count_tokens status=success dur={int((time.monotonic()-start)*1000)}ms "
            f"in={token_count}"
        )
        return CountTokensResponse(input_tokens=token_count)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        logger.info(
            f"[REQ] id=count ip={ip} model={request_data.model} "
            f"op=count_tokens status=error_{exc.status_code} "
            f"dur={int((time.monotonic()-start)*1000)}ms "
            f"err={detail.get('type','')}: {detail.get('message','')}"
        )
        raise
    except Exception as e:
        logger.error(f"count_tokens error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"type": "api_error", "message": f"Internal error: {str(e)}"},
        )
