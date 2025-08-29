# AI-related API endpoints

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from config import AVAILABLE_INDICATORS
from ai_features import get_ai_suggestion, get_local_ollama_models, AIRequest
from logging_config import logger

async def ai_suggestion_endpoint(request_data: AIRequest):
    return await get_ai_suggestion(request_data)

async def get_local_ollama_models_endpoint():
    return await get_local_ollama_models()

async def get_available_indicators_endpoint():
    """Returns the list of available technical indicators."""
    return JSONResponse(AVAILABLE_INDICATORS)