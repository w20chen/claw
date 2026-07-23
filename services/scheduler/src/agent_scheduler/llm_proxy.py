from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from agent_scheduler.config import SchedulerConfig
from agent_scheduler.trace import AgentTestBenchTraceWriter


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


async def proxy_models(request: Request, config: SchedulerConfig) -> Response:
    upstream = _upstream_url(config, request.url.path)
    if upstream is None:
        return _not_configured()
    headers = _forward_headers(request, config)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request("GET", upstream, headers=headers, params=request.query_params)
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=_response_headers(response),
        media_type=response.headers.get("content-type"),
    )


async def proxy_chat_completions(
    request: Request,
    config: SchedulerConfig,
    trace_writer: AgentTestBenchTraceWriter | None,
) -> Response:
    upstream = _upstream_url(config, request.url.path)
    if upstream is None:
        return _not_configured()

    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError:
        payload = {}

    stream = bool(payload.get("stream"))
    started_at = time.time()
    action_id = f"llm-proxy-{uuid4()}"
    headers = _forward_headers(request, config)

    if stream:
        return StreamingResponse(
            _stream_chat(
                upstream,
                headers=headers,
                body=body,
                payload=payload,
                trace_writer=trace_writer,
                action_id=action_id,
                started_at=started_at,
            ),
            media_type="text/event-stream",
        )

    async with httpx.AsyncClient(timeout=None) as client:
        try:
            response = await client.post(upstream, headers=headers, content=body)
        except Exception as exc:
            _record_proxy_trace(
                trace_writer,
                action_id=action_id,
                payload=payload,
                response_payload=None,
                started_at=started_at,
                status_code=502,
                stream=False,
                error=str(exc),
            )
            return JSONResponse({"error": {"message": str(exc), "type": "proxy_error"}}, status_code=502)

    response_payload = _json_or_text(response.content)
    _record_proxy_trace(
        trace_writer,
        action_id=action_id,
        payload=payload,
        response_payload=response_payload,
        started_at=started_at,
        status_code=response.status_code,
        stream=False,
        error=None if response.status_code < 400 else f"upstream_http_{response.status_code}",
    )
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=_response_headers(response),
        media_type=response.headers.get("content-type"),
    )


async def _stream_chat(
    upstream: str,
    *,
    headers: dict[str, str],
    body: bytes,
    payload: dict[str, Any],
    trace_writer: AgentTestBenchTraceWriter | None,
    action_id: str,
    started_at: float,
):
    chunks: list[dict[str, Any]] = []
    status_code = 200
    error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", upstream, headers=headers, content=body) as response:
                status_code = response.status_code
                async for chunk in response.aiter_bytes():
                    for event in _parse_sse_chunk(chunk):
                        if event is not None:
                            chunks.append(event)
                    yield chunk
    except Exception as exc:
        status_code = 502
        error = str(exc)
        yield f"data: {json.dumps({'error': {'message': str(exc), 'type': 'proxy_error'}})}\n\n".encode(
            "utf-8"
        )
    finally:
            _record_proxy_trace(
                trace_writer,
                action_id=action_id,
                payload=payload,
                response_payload={"message": _message_from_stream_chunks(chunks)},
                started_at=started_at,
                status_code=status_code,
                stream=True,
                error=error if error else (None if status_code < 400 else f"upstream_http_{status_code}"),
            )


def _record_proxy_trace(
    trace_writer: AgentTestBenchTraceWriter | None,
    *,
    action_id: str,
    payload: dict[str, Any],
    response_payload: Any | None,
    started_at: float,
    status_code: int,
    stream: bool,
    error: str | None,
) -> None:
    if trace_writer is None:
        return
    trace_writer.record_llm_proxy_call(
        action_id=action_id,
        provider="llm-proxy",
        model=payload.get("model") if isinstance(payload.get("model"), str) else None,
        messages_in=payload.get("messages"),
        content=_content_from_response(response_payload),
        raw_request=payload,
        raw_response=response_payload,
        ts_start=started_at,
        ts_end=time.time(),
        status_code=status_code,
        stream=stream,
        error=error,
    )


def _upstream_url(config: SchedulerConfig, path: str) -> str | None:
    if not config.llm_proxy_enabled or not config.llm_proxy_upstream_base_url:
        return None
    base = config.llm_proxy_upstream_base_url.rstrip("/")
    if path.startswith("/v1/"):
        suffix = path[len("/v1") :]
    else:
        suffix = path
    return base + suffix


def _forward_headers(request: Request, config: SchedulerConfig) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }
    if config.llm_proxy_upstream_api_key:
        headers["authorization"] = f"Bearer {config.llm_proxy_upstream_api_key}"
    return headers


def _response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _not_configured() -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "message": "AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL is not configured",
                "type": "llm_proxy_not_configured",
            }
        },
        status_code=502,
    )


def _json_or_text(content: bytes) -> Any:
    try:
        return json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return content.decode("utf-8", errors="replace")


def _parse_sse_chunk(chunk: bytes) -> list[dict[str, Any] | None]:
    events: list[dict[str, Any] | None] = []
    text = chunk.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            events.append(None)
            continue
        try:
            events.append(json.loads(data))
        except json.JSONDecodeError:
            pass
    return events


def _content_from_response(response_payload: Any | None) -> Any | None:
    if response_payload is None:
        return None
    if isinstance(response_payload, dict) and "message" in response_payload:
        message = response_payload.get("message")
        if isinstance(message, dict):
            return message.get("content")
    if not isinstance(response_payload, dict):
        return None
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if isinstance(message, dict):
        return message.get("content")
    return first.get("text")


def _content_from_stream_chunks(chunks: list[dict[str, Any]]) -> str:
    return str(_message_from_stream_chunks(chunks).get("content") or "")


def _message_from_stream_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    finish_reason: str | None = None
    for chunk in chunks:
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            if isinstance(choice.get("finish_reason"), str):
                finish_reason = choice["finish_reason"]
            delta = choice.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                parts.append(delta["content"])
            if isinstance(delta, dict) and isinstance(delta.get("tool_calls"), list):
                _merge_tool_call_deltas(tool_calls, delta["tool_calls"])
            elif isinstance(choice.get("text"), str):
                parts.append(choice["text"])
    message: dict[str, Any] = {"role": "assistant", "content": "".join(parts)}
    if tool_calls:
        message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
    if finish_reason is not None:
        message["finish_reason"] = finish_reason
    return message


def _merge_tool_call_deltas(
    output: dict[int, dict[str, Any]], deltas: list[Any]
) -> None:
    for item in deltas:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int):
            index = len(output)
        current = output.setdefault(index, {"index": index, "type": "function", "function": {}})
        if isinstance(item.get("id"), str):
            current["id"] = item["id"]
        if isinstance(item.get("type"), str):
            current["type"] = item["type"]
        function = item.get("function")
        if isinstance(function, dict):
            current_function = current.setdefault("function", {})
            if isinstance(function.get("name"), str):
                current_function["name"] = function["name"]
            if isinstance(function.get("arguments"), str):
                current_function["arguments"] = (
                    str(current_function.get("arguments") or "") + function["arguments"]
                )
