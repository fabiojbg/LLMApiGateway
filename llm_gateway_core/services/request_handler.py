from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from fastapi.responses import StreamingResponse

from ..config.settings import settings


_SSE_EVENT_DELIMITER = re.compile(br"\r?\n\r?\n")


@dataclass(frozen=True)
class SSEEvent:
    """A parsed server-sent event and its combined data field."""

    raw: bytes
    data: str | None


class SSEParser:
    """Incrementally parse complete SSE events from arbitrary byte chunks."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        self._buffer.extend(chunk)
        events: list[SSEEvent] = []

        while match := _SSE_EVENT_DELIMITER.search(self._buffer):
            end = match.end()
            raw = bytes(self._buffer[:end])
            event_body = bytes(self._buffer[: match.start()])
            del self._buffer[:end]
            events.append(SSEEvent(raw=raw, data=self._extract_data(event_body)))

        return events

    @staticmethod
    def _extract_data(event_body: bytes) -> str | None:
        data_lines: list[str] = []
        for raw_line in event_body.replace(b"\r\n", b"\n").split(b"\n"):
            if raw_line.startswith(b":"):
                continue
            field, separator, value = raw_line.partition(b":")
            if field != b"data":
                continue
            if separator and value.startswith(b" "):
                value = value[1:]
            data_lines.append(value.decode("utf-8"))
        return "\n".join(data_lines) if data_lines else None


def _parse_data_payload(data: str) -> dict | None:
    if data.strip() == "[DONE]":
        return None
    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        raise ValueError("SSE data payload must be a JSON object")
    return parsed


def _stream_error_detail(event_data: str, payload: dict) -> str | None:
    if "error" not in payload and "detail" not in payload:
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error or payload.get("detail") or event_data)


async def _close_stream(response: httpx.Response) -> None:
    if not response.is_closed:
        await response.aclose()


async def make_llm_request(
    http_client: httpx.AsyncClient,
    target_url: str,
    headers: dict,
    payload: dict,
    is_streaming: bool,
):
    """Make one downstream request using the application-owned HTTP client."""
    payload_to_log = copy.deepcopy(payload)
    payload_to_log["messages"] = "<REMOVED>"
#    if "tools" in payload_to_log:
#        payload_to_log["tools"] = "<REMOVED>"
    logging.debug(
        "make_llm_request(): Sending request for model '%s'. Payload: %s",
        payload_to_log.get("model"),
        payload_to_log,
    )

    try:
        if not is_streaming:
            response = await http_client.post(target_url, headers=headers, json=payload)
            logging.debug("Response received from %s", target_url)

            if response.status_code >= 400:
                error_detail = response.text
                logging.warning(
                    "Downstream error %s from %s: %s",
                    response.status_code,
                    target_url,
                    error_detail,
                )
                return None, error_detail

            try:
                response_json = response.json()
            except ValueError as json_error:
                error_detail = (
                    f"Invalid JSON response from {target_url}. "
                    f"Error={json_error}. Response={response.text[:1000]}..."
                )
                logging.error(error_detail)
                return None, error_detail

            if "error" in response_json or "detail" in response_json:
                error = response_json.get("error")
                if isinstance(error, dict):
                    error = error.get("message") or error
                error_detail = str(error or response_json.get("detail"))
                logging.warning(
                    "Error detected in non-stream response from %s: %s",
                    target_url,
                    error_detail,
                )
                return None, error_detail
            return response_json, None

        request = http_client.build_request(
            "POST", target_url, headers=headers, json=payload
        )
        response = await http_client.send(request, stream=True)

        if response.status_code >= 400:
            try:
                error_detail = (await response.aread()).decode(
                    "utf-8", errors="replace"
                )
            finally:
                await _close_stream(response)
            logging.error(
                "Downstream error %s from %s: %s",
                response.status_code,
                target_url,
                error_detail,
            )
            return None, error_detail

        parser = SSEParser()
        upstream_iterator = response.aiter_bytes()
        primed_chunks: list[bytes] = []
        prefetched_bytes = 0
        prefetched_events = 0
        first_data_seen = False

        try:
            async for chunk in upstream_iterator:
                if not chunk:
                    continue
                primed_chunks.append(chunk)
                prefetched_bytes += len(chunk)
                events = parser.feed(chunk)
                prefetched_events += len(events)
                for event in events:
                    if event.data is None or event.data.strip() == "[DONE]":
                        continue
                    try:
                        event_payload = _parse_data_payload(event.data)
                    except (UnicodeDecodeError, ValueError) as parse_error:
                        await _close_stream(response)
                        return None, (
                            f"Invalid SSE JSON response from {target_url}: {parse_error}"
                        )
                    if event_payload is None:
                        continue
                    error_detail = _stream_error_detail(event.data, event_payload)
                    if error_detail is not None:
                        await _close_stream(response)
                        return None, error_detail
                    first_data_seen = True
                    break
                if first_data_seen:
                    break
                if (
                    prefetched_bytes > settings.http_stream_prefetch_max_bytes
                    or prefetched_events > settings.http_stream_prefetch_max_events
                ):
                    await _close_stream(response)
                    return None, (
                        f"Provider stream prefetch limit exceeded for {target_url} "
                        f"({prefetched_bytes} bytes, {prefetched_events} events)"
                    )
        except BaseException:
            await _close_stream(response)
            raise

        if not first_data_seen:
            await _close_stream(response)
            return None, f"Empty provider stream from {target_url}"

        async def combined_generator() -> AsyncIterator[bytes]:
            stream_parser = parser
            try:
                for primed_chunk in primed_chunks:
                    yield primed_chunk

                async for chunk in upstream_iterator:
                    if not chunk:
                        continue
                    stop_after_chunk = False
                    for event in stream_parser.feed(chunk):
                        if event.data is None or event.data.strip() == "[DONE]":
                            continue
                        try:
                            event_payload = _parse_data_payload(event.data)
                        except (UnicodeDecodeError, ValueError) as parse_error:
                            logging.warning(
                                "Invalid SSE event after streaming started from %s: %s",
                                target_url,
                                parse_error,
                            )
                            stop_after_chunk = True
                            break
                        if event_payload is None:
                            continue
                        if error_detail := _stream_error_detail(
                            event.data, event_payload
                        ):
                            logging.warning(
                                "Error after streaming started from %s: %s",
                                target_url,
                                error_detail,
                            )
                            stop_after_chunk = True
                            break
                    yield chunk
                    if stop_after_chunk:
                        break
            finally:
                await _close_stream(response)

        return (
            StreamingResponse(
                combined_generator(),
                media_type="text/event-stream",
                headers={"X-Accel-Buffering": "no"},
            ),
            None,
        )

    except httpx.RequestError as error:
        error_detail = f"RequestError connecting to {target_url}: {error}"
        logging.error(error_detail, exc_info=True)
        return None, error_detail
    except Exception as error:
        error_detail = f"Unexpected error during request to {target_url}: {error}"
        logging.error(error_detail, exc_info=True)
        return None, error_detail
