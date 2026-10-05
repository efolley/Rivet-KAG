"""Best-effort async Kafka producer. Publishing is fire-and-forget: a Kafka outage must never
block or fail the user-facing request it's reporting on (see src/api/routes/chat.py and
src/api/routes/files.py, which call publish_event after already building their response).
"""

import asyncio
import json
import logging
from functools import lru_cache
from typing import Any

from aiokafka import AIOKafkaProducer

from src.config import get_settings

log = logging.getLogger(__name__)

_start_lock = asyncio.Lock()
_started = False


@lru_cache
def _producer() -> AIOKafkaProducer:
    return AIOKafkaProducer(bootstrap_servers=get_settings().kafka_bootstrap_servers)


async def publish_event(topic: str, payload: dict[str, Any]) -> None:
    """Serializes `payload` as JSON and sends it to `topic`. Swallows and logs any failure
    (unreachable broker, serialization error) instead of raising."""
    global _started
    try:
        producer = _producer()
        if not _started:
            async with _start_lock:
                if not _started:
                    await producer.start()
                    _started = True
        await producer.send_and_wait(topic, json.dumps(payload).encode("utf-8"))
    except Exception:
        log.warning("Could not publish to Kafka topic %s", topic, exc_info=True)


async def shutdown_producer() -> None:
    """Called from the app's lifespan shutdown so the producer closes its connections cleanly."""
    global _started
    if _started:
        await _producer().stop()
        _started = False
