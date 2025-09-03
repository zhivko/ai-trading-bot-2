# Drawing management utilities

import json
import uuid
from typing import Dict, Any, List, Optional
from fastapi import Request
from pydantic import BaseModel
from redis_utils import get_redis_connection, get_drawings_redis_key
from logging_config import logger
from config import SUPPORTED_SYMBOLS

class DrawingData(BaseModel):
    symbol: str
    type: str
    start_time: int
    end_time: int
    start_price: float
    end_price: float
    subplot_name: str  # Identifies the main plot or subplot (e.g., "BTCUSDT" or "BTCUSDT-MACD")
    resolution: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None  # New field for additional properties

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

async def save_drawing(drawing_data: Dict[str, Any], request: Request) -> str:
    redis = await get_redis_connection()
    symbol = drawing_data["symbol"]
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"Unsupported symbol: {symbol}")
    key = get_drawings_redis_key(symbol, request)
    drawings_data_str = await redis.get(key)
    drawings = json.loads(drawings_data_str) if drawings_data_str else []
    drawing_with_id = {**drawing_data, "id": str(uuid.uuid4())}
    drawings.append(drawing_with_id)
    await redis.set(key, json.dumps(drawings))

    return drawing_with_id["id"]

async def get_drawings(symbol: str, request: Request = None, resolution: Optional[str] = None, email: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves drawings for a given symbol from Redis.
    If a resolution is provided, it filters drawings to only include those
    matching the specified resolution.
    """
    redis = await get_redis_connection()
    key = get_drawings_redis_key(symbol, request, email)

    drawings_data_str = await redis.get(key)
    all_drawings = json.loads(drawings_data_str) if drawings_data_str else []

    if not resolution:
        # If no resolution is specified, return all drawings for backward compatibility or other uses.
        return all_drawings

    # If a resolution is specified, filter the drawings.
    # A drawing is included if its 'resolution' property matches the requested resolution.
    # Drawings without a 'resolution' property will be excluded.
    filtered_drawings = [d for d in all_drawings if d.get("resolution") == resolution]
    logger.info(f"get_drawings for {symbol} with resolution '{resolution}': found {len(all_drawings)} total, returning {len(filtered_drawings)} filtered.")
    return filtered_drawings

async def delete_drawing(symbol: str, drawing_id: str, request: Request = None, email: Optional[str] = None) -> bool:
    redis = await get_redis_connection()
    key = get_drawings_redis_key(symbol, request, email)
    drawings_data_str = await redis.get(key)
    if not drawings_data_str:
        return False
    drawings = json.loads(drawings_data_str)
    original_len = len(drawings)
    drawings = [d for d in drawings if d.get("id") != drawing_id]
    if len(drawings) == original_len:
        return False
    await redis.set(key, json.dumps(drawings))
    return True

async def update_drawing(symbol: str, drawing_id: str, drawing_data: DrawingData, request: Request = None, email: Optional[str] = None) -> bool:
    redis = await get_redis_connection()
    key = get_drawings_redis_key(symbol, request, email)
    drawings_data_str = await redis.get(key)
    if not drawings_data_str:
        return False
    drawings = json.loads(drawings_data_str)
    found = False
    for i, drawing_item in enumerate(drawings):
        if not isinstance(drawing_item, dict):
            continue
        if drawing_item.get("id") == drawing_id:
            # Preserve existing properties to prevent them from being overwritten.
            existing_properties = drawing_item.get('properties', {})
            update_payload = drawing_data.to_dict() if hasattr(drawing_data, 'to_dict') else {}

            # If the incoming data has properties, merge them with existing ones.
            if isinstance(update_payload, dict) and update_payload.get('properties'):
                if isinstance(existing_properties, dict) and isinstance(update_payload['properties'], dict):
                    existing_properties.update(update_payload['properties'])

            # Ensure properties are properly set
            if not isinstance(existing_properties, dict):
                existing_properties = {}

            update_payload['properties'] = existing_properties
            update_payload['id'] = drawing_id  # Ensure the ID is preserved.

            if isinstance(update_payload, dict):
                drawings[i] = update_payload
            found = True

            break
    if not found:
        logger.info(f"Drawing {drawing_id} not found.")
        return False

    await redis.set(key, json.dumps(drawings))
    logger.info(f"Drawing {drawing_id} updated.")

    return True