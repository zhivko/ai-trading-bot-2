from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection accepted.")
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"Received: {data}")
            await websocket.send_text(f"Message text was: {data}")
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)

if __name__ == "__main__":
    uvicorn.run(app, host="192.168.1.52", port=8000)
