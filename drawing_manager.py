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
    type: Optional[str] = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    start_price: Optional[float] = None
    end_price: Optional[float] = None
    subplot_name: Optional[str] = None  # Identifies the main plot or subplot (e.g., "BTCUSDT" or "BTCUSDT-MACD")
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
    #logger.info(f"Drawing {drawing_with_id['id']} saved.")
    #logger.info(f"Json of drawing {drawings_data_str}")

    return drawing_with_id["id"]

async def get_drawings(symbol: str, request: Request = None, resolution: Optional[str] = None, email: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves drawings for a given symbol from Redis.
    If a resolution is provided, it filters drawings to only include those
    matching the specified resolution.
    """
    redis = await get_redis_connection()
    key = get_drawings_redis_key(symbol, request, email)

    logger.info(f"🔍 GET_DRAWINGS: Retrieving drawings from Redis key {key}")
    drawings_data_str = await redis.get(key)
    all_drawings = json.loads(drawings_data_str) if drawings_data_str else []
    
    logger.info(f"🔍 GET_DRAWINGS: Found {len(all_drawings)} drawings in Redis key {key}")
    if all_drawings:
        logger.info(f"🔍 GET_DRAWINGS: Available drawing IDs: {[d.get('id') for d in all_drawings if isinstance(d, dict)]}")
        # Log properties of each drawing for debugging
        for drawing in all_drawings:
            if isinstance(drawing, dict):
                drawing_id = drawing.get('id')
                drawing_props = drawing.get('properties', {})
                logger.info(f"🔍 GET_DRAWINGS: Drawing {drawing_id} properties: {drawing_props}")

    if not resolution:
        # If no resolution is specified, return all drawings for backward compatibility or other uses.
        logger.info(f"🔍 GET_DRAWINGS: Returning all {len(all_drawings)} drawings (no resolution filter)")
        return all_drawings

    # If a resolution is specified, filter the drawings.
    # A drawing is included if its 'resolution' property matches the requested resolution.
    # Drawings without a 'resolution' property will be excluded.
    filtered_drawings = [d for d in all_drawings if d.get("resolution") == resolution]
    logger.info(f"🔍 GET_DRAWINGS: After resolution filter '{resolution}': found {len(all_drawings)} total, returning {len(filtered_drawings)} filtered.")
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
    redis_key = get_drawings_redis_key(symbol, request, email)
    drawings_data_str = await redis.get(redis_key)
    if not drawings_data_str:
        return False
    drawings = json.loads(drawings_data_str)
    found = False
    for i, drawing_item in enumerate(drawings):
        if not isinstance(drawing_item, dict):
            continue
        if drawing_item.get("id") == drawing_id:
            # Preserve all existing fields to prevent them from being overwritten with null values
            update_payload = drawing_data.to_dict() if hasattr(drawing_data, 'to_dict') else {}
            
            # Merge existing fields with new data, preserving existing values when new data is missing/null
            for key, value in drawing_item.items():
                # If the key is not in update_payload or the value is None/null, preserve the existing value
                if key not in update_payload or update_payload.get(key) is None:
                    update_payload[key] = value
            
            # Special handling for properties - merge them properly
            existing_properties = drawing_item.get('properties', {})
            if isinstance(update_payload, dict) and update_payload.get('properties'):
                if isinstance(existing_properties, dict) and isinstance(update_payload['properties'], dict):
                    # Merge new properties with existing ones
                    merged_properties = existing_properties.copy()
                    merged_properties.update(update_payload['properties'])
                    update_payload['properties'] = merged_properties
            else:
                # If no new properties, preserve existing ones
                update_payload['properties'] = existing_properties

            # Ensure ID is preserved
            update_payload['id'] = drawing_id

            if isinstance(update_payload, dict):
                drawings[i] = update_payload
            found = True

            break
    if not found:
        logger.info(f"Drawing {drawing_id} not found.")
        return False

    await redis.set(redis_key, json.dumps(drawings))
    logger.info(f"Drawing {drawing_id} updated.")

    return True


async def update_drawing_properties(symbol: str, drawing_id: str, properties: Dict[str, Any], email: Optional[str] = None) -> bool:
    """
    Update only the properties of a drawing without affecting other fields.
    """
    redis = await get_redis_connection()
    key = get_drawings_redis_key(symbol, None, email)
    logger.info(f"🔧 UPDATE_DRAWING_PROPERTIES: Looking for drawing {drawing_id} in Redis key {key}")
    
    drawings_data_str = await redis.get(key)
    if not drawings_data_str:
        logger.warning(f"⚠️ UPDATE_DRAWING_PROPERTIES: No drawings found in Redis key {key}")
        return False
    
    drawings = json.loads(drawings_data_str)
    logger.info(f"🔧 UPDATE_DRAWING_PROPERTIES: Found {len(drawings)} drawings in Redis, looking for ID {drawing_id}")
    
    found = False
    for i, drawing_item in enumerate(drawings):
        if not isinstance(drawing_item, dict):
            continue
        if drawing_item.get("id") == drawing_id:
            logger.info(f"🔧 UPDATE_DRAWING_PROPERTIES: Found drawing {drawing_id}, updating properties")
            logger.info(f"🔧 UPDATE_DRAWING_PROPERTIES: Old properties: {drawing_item.get('properties', {})}")
            logger.info(f"🔧 UPDATE_DRAWING_PROPERTIES: New properties: {properties}")
            
            # Merge new properties with existing properties
            existing_properties = drawing_item.get('properties', {})
            if isinstance(existing_properties, dict) and isinstance(properties, dict):
                # Create a copy of existing properties and update with new ones
                merged_properties = existing_properties.copy()
                merged_properties.update(properties)
                drawing_item['properties'] = merged_properties
                logger.info(f"🔧 UPDATE_DRAWING_PROPERTIES: Merged properties for drawing {drawing_id}: {drawing_item['properties']}")
            else:
                # If one of them is not a dict, just use the new properties
                drawing_item['properties'] = properties
                logger.info(f"🔧 UPDATE_DRAWING_PROPERTIES: Replaced properties for drawing {drawing_id}: {drawing_item['properties']}")
            found = True
            break
    
    if not found:
        logger.warning(f"❌ UPDATE_DRAWING_PROPERTIES: Drawing {drawing_id} not found for properties update in key {key}")
        logger.info(f"🔧 UPDATE_DRAWING_PROPERTIES: Available drawing IDs: {[d.get('id') for d in drawings if isinstance(d, dict)]}")
        return False

    await redis.set(key, json.dumps(drawings))
    logger.info(f"💾 UPDATE_DRAWING_PROPERTIES: Successfully saved updated drawings to Redis key {key}")
    logger.info(f"🔧 UPDATE_DRAWING_PROPERTIES: Updated drawing {drawing_id} properties in Redis")

    return True
