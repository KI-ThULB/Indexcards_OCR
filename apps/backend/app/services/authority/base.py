"""Shared async HTTP helper with exponential-backoff retry for authority API calls."""
import asyncio
import aiohttp
from typing import Optional


INDEXCARDS_USER_AGENT = "IndexcardsOCR/1.0 (contact@thulb.uni-jena.de)"


async def fetch_with_retry(
    url: str,
    *,
    method: str = "GET",
    params: Optional[dict] = None,
    data: Optional[dict] = None,
    headers: Optional[dict] = None,
    max_retries: int = 3,
    backoff_base: float = 1.0,
) -> dict:
    """Perform an HTTP request with 3-attempt exponential backoff (1s/2s/4s).
    Handles:
      - HTTP 429: honor Retry-After header if present, else use backoff
      - HTTP 5xx: retry with backoff
      - Network errors (ClientError, TimeoutError): retry with backoff
    Raises RuntimeError after max_retries failures.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        wait = backoff_base * (2 ** attempt)  # 1s, 2s, 4s
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if method.upper() == "POST":
                    req_cm = session.post(url, params=params, data=data, headers=headers)
                else:
                    req_cm = session.get(url, params=params, headers=headers)
                async with req_cm as resp:
                    if resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", wait))
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status >= 500:
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_exc = e
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)
    raise RuntimeError(
        f"Authority API request to {url} failed after {max_retries} attempts"
    ) from last_exc
