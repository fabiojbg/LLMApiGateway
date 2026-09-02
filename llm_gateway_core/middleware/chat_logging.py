import asyncio
import codecs
import glob
import logging
import os
from datetime import datetime
from pprint import pformat
from typing import Callable
from uuid import uuid4

import json5
from fastapi import Request, Response
from fastapi.responses import StreamingResponse

from ..config.settings import settings
from ..db.tokens_usage_db import TokensUsageDB

logger = logging.getLogger(__name__)

# Kept as a lazy compatibility fallback for direct middleware use and tests.
# The application-provided database in request.app.state is preferred.
tokens_usage_db: TokensUsageDB | None = None


def _default_tokens_usage() -> dict:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "cost": 0,
    }


def _get_default_tokens_usage_db() -> TokensUsageDB:
    global tokens_usage_db
    if tokens_usage_db is None:
        tokens_usage_db = TokensUsageDB()
    return tokens_usage_db


def write_log(
    req_headers,
    req_body_str,
    llm_response_accum,
    tokens_usage,
    usage_db: TokensUsageDB | None = None,
):
    try:
        log_time = datetime.now()
        timestamp = log_time.strftime("%Y-%m-%d_%H-%M-%S.%f")
        filename = f"{timestamp}_{uuid4().hex}.txt"
        division_line = "-" * 100
        model = f"Model: {tokens_usage['model']}\n" if "model" in tokens_usage else ""
        provider = (
            f"Provider: {tokens_usage['provider']}\n\n"
            if "provider" in tokens_usage
            else ""
        )
        response_text = (
            llm_response_accum
            if llm_response_accum and llm_response_accum.strip()
            else "<No content. This may be caused by the call to 'tools' or 'mcps' as the model's last request>"
        )
        log_content = (
            f"{division_line}\nTokens Usage:\n-{division_line}\n\n"
            f"Input: {tokens_usage['prompt_tokens']}\n"
            f"Output: {tokens_usage['completion_tokens']}\n"
            f"Cached: {tokens_usage['cached_tokens']}\n"
            f"Reasoning: {tokens_usage['reasoning_tokens']}\n"
            f"Total: {tokens_usage['total_tokens']}\n"
            f"Cost: ${tokens_usage['cost']:0.6f}\n"
            f"{model}"
            f"{provider}"
            f"{division_line}\nRequest Headers:\n{division_line}\n\n"
            f"{pformat(req_headers, indent=2)}\n\n"
            f"{division_line}\nRequest Body:\n-{division_line}\n\n{req_body_str}\n\n"
            f"{division_line}\nLLM Response:\n{division_line}\n\n{response_text}"
        )
        os.makedirs("logs", exist_ok=True)
        log_path = os.path.join("./logs", filename)

        with open(log_path, "x", encoding="utf-8") as log_file:
            log_content = log_content.replace("\\n\\n", "\r\n\r\n").replace(
                "\\n", "\r\n"
            )
            log_file.write(log_content)

        try:
            target_usage_db = (
                usage_db if usage_db is not None else _get_default_tokens_usage_db()
            )
            target_usage_db.insert_usage(tokens_usage)
        except Exception as db_error:
            logger.error(
                "Failed to insert token usage data into database: %s",
                db_error,
                exc_info=True,
            )

        log_files = sorted(
            glob.glob(os.path.join("./logs", "*.txt")), key=os.path.getmtime
        )
        max_logs = settings.log_file_limit or 50
        while len(log_files) > max_logs:
            try:
                os.remove(log_files.pop(0))
            except Exception:
                pass
    except Exception as exc:
        logger.error("Failed to write chat log: %s", exc, exc_info=True)


class ChatLogCollector:
    """Incrementally parses a response while retaining only bounded log text."""

    def __init__(
        self,
        req_headers: dict,
        req_body_str: str,
        is_event_stream: bool,
        usage_db: TokensUsageDB | None = None,
        response_max_chars: int | None = None,
    ):
        self.req_headers = req_headers
        self.req_body_str = req_body_str
        self.is_event_stream = is_event_stream
        self.usage_db = usage_db
        self.response_max_chars = max(
            0,
            response_max_chars
            if response_max_chars is not None
            else settings.log_chat_response_max_chars,
        )
        self.llm_response_accum = ""
        self.tokens_usage = _default_tokens_usage()
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._event_buffer = ""
        self._non_stream_body_parts: list[str] = []
        self._persist_started = False

    def feed(self, chunk: bytes | str) -> None:
        if isinstance(chunk, bytes):
            text = self._decoder.decode(chunk)
        else:
            text = chunk
        self._feed_text(text)

    def finish(self) -> None:
        remaining_text = self._decoder.decode(b"", final=True)
        self._feed_text(remaining_text)

        if self.is_event_stream:
            if self._event_buffer.strip():
                self._process_event(self._event_buffer)
            self._event_buffer = ""
            return

        response_body = "".join(self._non_stream_body_parts)
        self._non_stream_body_parts.clear()
        if response_body:
            self._process_json_payload(response_body)

    async def persist_once(self) -> None:
        if self._persist_started:
            return
        self._persist_started = True
        persist_task = asyncio.create_task(
            asyncio.to_thread(
                write_log,
                self.req_headers,
                self.req_body_str,
                self.llm_response_accum,
                self.tokens_usage,
                self.usage_db,
            )
        )
        try:
            await asyncio.shield(persist_task)
        except asyncio.CancelledError:
            # Shield keeps the blocking persistence alive. Wait for it before
            # propagating cancellation so the final record cannot be dropped.
            await persist_task
            raise

    def _feed_text(self, text: str) -> None:
        if not text:
            return
        if not self.is_event_stream:
            self._non_stream_body_parts.append(text)
            return

        self._event_buffer = (self._event_buffer + text).replace("\r\n", "\n")
        events = self._event_buffer.split("\n\n")
        self._event_buffer = events.pop()
        for event in events:
            self._process_event(event)

    def _process_event(self, event: str) -> None:
        data_lines = []
        for line in event.splitlines():
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        payload = "\n".join(data_lines).strip() if data_lines else event.strip()
        if not payload or payload == "[DONE]":
            return
        self._process_json_payload(payload)

    def _process_json_payload(self, payload: str) -> None:
        try:
            chunk_data = json5.loads(payload)
            if not isinstance(chunk_data, dict):
                return

            for choice in chunk_data.get("choices", []):
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                message = choice.get("message")
                if isinstance(delta, dict):
                    self._append_response(delta.get("content"))
                elif isinstance(message, dict):
                    self._append_response(message.get("content"))

            if "usage" in chunk_data:
                self.tokens_usage = get_token_usage(chunk_data)
            if "error" in chunk_data:
                self._append_response(payload)
        except Exception as exc:
            logger.error(
                "ChatLogging: error processing response payload: %s: %s",
                payload,
                exc,
                exc_info=True,
            )

    def _append_response(self, content: object) -> None:
        if not isinstance(content, str) or not content:
            return
        remaining = self.response_max_chars - len(self.llm_response_accum)
        if remaining > 0:
            self.llm_response_accum += content[:remaining]


def _request_usage_db(request: Request) -> TokensUsageDB | None:
    app_state = getattr(getattr(request, "app", None), "state", None)
    return getattr(app_state, "tokens_usage_db", None)


async def log_chat_completions(request: Request, call_next: Callable) -> Response:
    if not request.url.path.endswith("/chat/completions"):
        return await call_next(request)

    try:
        req_body_bytes = await request.body()
        req_body_str = req_body_bytes.decode("utf-8", errors="replace")
        request_max_chars = max(0, settings.log_chat_request_max_chars)
        req_body_str = req_body_str[:request_max_chars]
        req_headers = dict(request.headers)
    except Exception as exc:
        logger.error(
            "Error capturing request body in log_chat middleware: %s",
            exc,
            exc_info=True,
        )
        return await call_next(request)

    usage_db = _request_usage_db(request)
    try:
        response = await call_next(request)
    except BaseException:
        collector = ChatLogCollector(req_headers, req_body_str, False, usage_db)
        await collector.persist_once()
        raise

    is_event_stream = "text/event-stream" in response.headers.get(
        "content-type", ""
    )
    is_streaming_response = isinstance(response, StreamingResponse) or (
        "StreamingResponse" in type(response).__name__
    )
    collector = ChatLogCollector(
        req_headers,
        req_body_str,
        is_event_stream,
        usage_db,
    )

    if is_streaming_response:
        original_iterator = response.body_iterator

        async def collecting_generator():
            try:
                async for chunk in original_iterator:
                    collector.feed(chunk)
                    yield chunk
            finally:
                collector.finish()
                await collector.persist_once()

        response.body_iterator = collecting_generator()
    else:
        body = getattr(response, "body", b"")
        if body:
            collector.feed(body)
        collector.finish()
        await collector.persist_once()

    return response


def get_token_usage(chunk_data):
    """Extract token usage information from an OpenAI-compatible payload."""
    tokens_usage = _default_tokens_usage()
    try:
        if "usage" in chunk_data and isinstance(chunk_data["usage"], dict):
            usage = chunk_data["usage"]
            if "prompt_tokens" in usage:
                tokens_usage["prompt_tokens"] = usage["prompt_tokens"]
            if "completion_tokens" in usage:
                tokens_usage["completion_tokens"] = usage["completion_tokens"]
            if "total_tokens" in usage:
                tokens_usage["total_tokens"] = usage["total_tokens"]
            if "cost" in usage:
                tokens_usage["cost"] = usage["cost"]
            if (
                "completion_tokens_details" in usage
                and "reasoning_tokens" in usage["completion_tokens_details"]
            ):
                tokens_usage["reasoning_tokens"] = usage[
                    "completion_tokens_details"
                ]["reasoning_tokens"]
            if (
                "prompt_tokens_details" in usage
                and "cached_tokens" in usage["prompt_tokens_details"]
            ):
                tokens_usage["cached_tokens"] = usage["prompt_tokens_details"][
                    "cached_tokens"
                ]
            if tokens_usage["reasoning_tokens"] > 0:
                tokens_usage["completion_tokens"] -= tokens_usage[
                    "reasoning_tokens"
                ]
        if "provider" in chunk_data:
            tokens_usage["provider"] = chunk_data["provider"]
        if "model" in chunk_data:
            tokens_usage["model"] = chunk_data["model"]
    except Exception as exc:
        logger.error(
            "ChatLogging: error processing tokens usage: %s", exc, exc_info=True
        )

    return tokens_usage
