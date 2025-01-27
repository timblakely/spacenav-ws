import asyncio
import logging
import os
import pathlib

import fastapi
from fastapi import templating
from fastapi.middleware import cors
from spacenav_ws.mouse import session
from spacenav_ws import wamp
import uvicorn

logging.basicConfig(level=logging.INFO)

BASE_DIR = pathlib.Path(__file__).resolve().parent

ORIGINS = [
    "https://127.51.68.120",
    "https://127.51.68.120:8181",
    "https://3dconnexion.com",
    "https://cad.onshape.com",
]

app = fastapi.FastAPI()
templates = templating.Jinja2Templates(
    directory=os.path.join(BASE_DIR, "templates"))

app.add_middleware(
    cors.CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.route("/3dconnexion/nlproxy")
async def nlproxy(request):
  return fastapi.responses.JSONResponse({"port": "8181"})


RUNNING = True


@app.websocket("/")
@app.websocket("/3dconnexion")
async def websocket_endpoint(websocket: fastapi.WebSocket):
  logging.info('Accepting 3dmosue connection')
  wamp_session = wamp.WampSession(websocket)

  mouse = session.MouseSession(wamp_session)
  await mouse.begin()
  while RUNNING:
    await mouse.process()

  await mouse.shutdown()


# TODO(blakely): This realily isn't the proper way to do this, but at least it
# avoids the hang at the end waiting for the websocket to drop.
@app.on_event("shutdown")
def shutdown():
  global RUNNING
  RUNNING = False
  logging.info(f'   RUNNING: {RUNNING}')


@app.on_event("startup")
def shutdown():
  global RUNNING
  RUNNING = True
  logging.info(f'    RUNNING: {RUNNING}')


if __name__ == "__main__":
  uvicorn.run(
      "spacenav_ws.main:app",
      host="0.0.0.0",
      port=8000,
      reload=True,
      log_level="debug",
  )
