# Drawing-related API endpoints

import json
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from config import SUPPORTED_SYMBOLS
from drawing_manager import (
    save_drawing, get_drawings, delete_drawing, update_drawing,
    DrawingData
)
from logging_config import logger

async def get_drawings_api_endpoint(symbol: str, request: Request, resolution: str = None):
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)
    drawings = await get_drawings(symbol, request, resolution=resolution)
    return JSONResponse({"status": "success", "drawings": drawings})

async def save_drawing_api_endpoint(symbol: str, drawing_data: DrawingData, request: Request):
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)
    drawing_dict = drawing_data.to_dict()
    drawing_dict['symbol'] = symbol  # Ensure symbol from path is used
    drawing_id = await save_drawing(drawing_dict, request)
    return JSONResponse({"status": "success", "id": drawing_id})

async def delete_drawing_api_endpoint(symbol: str, drawing_id: str, request: Request):
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)
    deleted = await delete_drawing(symbol, drawing_id, request)
    if not deleted:
        return JSONResponse({"status": "error", "message": "Drawing not found"}, status_code=404)
    return JSONResponse({"status": "success"})

async def update_drawing_api_endpoint(symbol: str, drawing_id: str, drawing_data: DrawingData, request: Request):
    logger.info(f"PUT /update_drawing/{symbol}/{drawing_id} request received")
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)
    drawing_data.symbol = symbol  # Ensure symbol from path is used in the Pydantic model
    updated = await update_drawing(symbol, drawing_id, drawing_data, request)
    if not updated:
        return JSONResponse({"status": "error", "message": "Drawing not found"}, status_code=404)
    logger.info(f"PUT /update_drawing/{symbol}/{drawing_id} request completed successfully")
    return JSONResponse({"status": "success"})

async def delete_all_drawings_api_endpoint(symbol: str, request: Request):
    logger.info(f"DELETE /delete_all_drawings/{symbol} request received.")
    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"DELETE /delete_all_drawings: Unsupported symbol: {symbol}")
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)
    try:
        from redis_utils import get_redis_connection, get_drawings_redis_key
        redis = await get_redis_connection()
        key = get_drawings_redis_key(symbol, request)
        deleted_count = await redis.delete(key)  # delete returns the number of keys deleted
        logger.info(f"DELETE /delete_all_drawings/{symbol}: Deleted {deleted_count} Redis key(s).")
        return JSONResponse({"status": "success", "deleted_count": deleted_count})
    except Exception as e:
        logger.error(f"Error deleting all drawings for {symbol} from Redis: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": "Error deleting drawings"}, status_code=500)

async def save_shape_properties_api_endpoint(symbol: str, drawing_id: str, properties: dict, request: Request):
    if not isinstance(properties, dict):
        return JSONResponse({"status": "error", "message": "Invalid properties format"}, status_code=400)

    logger.info(f"POST /save_shape_properties/{symbol}/{drawing_id} request received with properties: {properties}")
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)

    # Fetch the existing drawing to merge properties
    existing_drawings = await get_drawings(symbol, request)
    if not isinstance(existing_drawings, list):
        existing_drawings = []

    existing_drawing = next((d for d in existing_drawings if isinstance(d, dict) and d.get("id") == drawing_id), None)

    if not existing_drawing or not isinstance(existing_drawing, dict):
        logger.warning(f"Shape {drawing_id} not found for symbol {symbol}.")
        return JSONResponse({"status": "error", "message": "Shape not found"}, status_code=404)

    # Create a DrawingData object from the existing drawing, then update properties and Y values
    try:
        if not all(key in existing_drawing for key in ['symbol', 'type']):
            return JSONResponse({"status": "error", "message": "Invalid drawing format"}, status_code=400)

        # Extract Y values and special fields from properties if provided
        start_price = properties.pop('start_price', existing_drawing.get('start_price'))
        end_price = properties.pop('end_price', existing_drawing.get('end_price'))
        buy_sent = properties.pop('buy_sent', existing_drawing.get('buy_sent', False))
        sell_sent = properties.pop('sell_sent', existing_drawing.get('sell_sent', False))

        drawing_data_instance = DrawingData(
            symbol=existing_drawing['symbol'],
            type=existing_drawing['type'],
            start_time=existing_drawing['start_time'],
            end_time=existing_drawing['end_time'],
            start_price=start_price,
            end_price=end_price,
            subplot_name=existing_drawing['subplot_name'],
            resolution=existing_drawing.get('resolution'),
            properties=existing_drawing.get('properties', {})  # Start with existing properties
        )
        # Merge new properties with existing ones
        if drawing_data_instance.properties is None:
            drawing_data_instance.properties = {}

        if properties:
            drawing_data_instance.properties.update(properties)

    except KeyError as e:
        logger.error(f"Missing key in existing drawing data for {drawing_id}: {e}")
        return JSONResponse({"status": "error", "message": f"Malformed existing drawing data: {e}"}, status_code=500)
    except Exception as e:
        logger.error(f"Error creating DrawingData instance from existing data: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": f"Internal server error: {e}"}, status_code=500)

    updated = await update_drawing(symbol, drawing_id, drawing_data_instance, request)
    if not updated:
        return JSONResponse({"status": "error", "message": "Failed to update shape properties"}, status_code=500)

    # Update special fields that need to be at the root level of the drawing
    # Fetch again to update buy_sent and sell_sent
    updated_drawings = await get_drawings(symbol, request)
    updated_drawing = next((d for d in updated_drawings if isinstance(d, dict) and d.get("id") == drawing_id), None)
    if updated_drawing:
        # Set the special fields directly on the drawing
        updated_drawing['buy_sent'] = buy_sent
        updated_drawing['sell_sent'] = sell_sent

        # Save back to Redis
        from redis_utils import get_redis_connection, get_drawings_redis_key
        redis = await get_redis_connection()
        key = get_drawings_redis_key(symbol, request)
        await redis.set(key, json.dumps(updated_drawings))
        logger.info(f"Special fields buy_sent={buy_sent}, sell_sent={sell_sent} updated successfully for drawing {drawing_id}")

    logger.info(f"Shape {drawing_id} properties and Y values updated successfully.")
    return JSONResponse({"status": "success", "message": "Shape properties updated successfully"})

async def get_shape_properties_api_endpoint(symbol: str, drawing_id: str, request: Request):
    logger.info(f"GET /get_shape_properties/{symbol}/{drawing_id} request received")

    # Validate that the symbol is supported
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)

    # Retrieve all drawings for the symbol from Redis
    from redis_utils import get_redis_connection
    redis = await get_redis_connection()
    email = request.session.get("email")
    drawings_key = f"drawings:{email}:{symbol}"
    drawings_data_str = await redis.get(drawings_key)

    if not drawings_data_str:
        raise HTTPException(status_code=404, detail="No drawings found for this symbol")

    drawings = json.loads(drawings_data_str)

    # Find the specific drawing by ID
    drawing = next((d for d in drawings if d.get("id") == drawing_id), None)

    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    # Extract the properties from the found drawing
    properties = drawing.get("properties", {})

    # Include Y values in the response
    properties_with_y = {
        **properties,
        "start_price": drawing.get("start_price"),
        "end_price": drawing.get("end_price"),
        "buy_sent": drawing.get("buy_sent", False),
        "sell_sent": drawing.get("sell_sent", False)
    }

    # Debug logging to understand the drawing state
    logger.info(f"Drawing data for {drawing_id}: alert_sent={drawing.get('alert_sent')}, alert_sent_time={drawing.get('alert_sent_time')}, properties.emailSent={properties.get('emailSent')}, properties.emailDate={properties.get('emailDate')}")

    # Manual emailSent from properties takes precedence (user-editable)
    email_sent = properties.get('emailSent')
    email_date = properties.get('emailDate')

    # If not manually set, fall back to legacy alert_sent behavior
    if email_sent is None:
        if drawing.get("alert_sent") is True:
            email_sent = True
            if drawing.get("alert_sent_time"):
                email_date = drawing["alert_sent_time"] * 1000  # convert to milliseconds for JS
        else:
            email_sent = False
            email_date = None

    # Update the response
    properties_with_y["emailSent"] = email_sent
    properties_with_y["emailDate"] = email_date

    logger.info(f"Returning shape properties for {drawing_id}: {properties_with_y}")
    return JSONResponse(content={"status": "success", "properties": properties_with_y})
