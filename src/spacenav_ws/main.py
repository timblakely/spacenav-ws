import asyncio
from asyncio import streams
import enum
import json
from pathlib import Path
import random
import socket
import string
from struct import unpack
import types
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
import numpy as np
import uvicorn

from spacenav_ws.event import from_message, MotionEvent

import logging

# logging.basicConfig(level=logging.DEBUG)

BASE_DIR = Path(__file__).resolve().parent

origins = [
    "https://127.51.68.120",
    "https://127.51.68.120:8181",
    "https://3dconnexion.com",
    "https://cad.onshape.com",
]

app = FastAPI()
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class WAMP_MSG_TYPE(enum.IntEnum):
  WELCOME = 0
  PREFIX = 1
  CALL = 2
  CALLRESULT = 3
  CALLERROR = 4
  SUBSCRIBE = 5
  UNSUBSCRIBE = 6
  PUBLISH = 7
  EVENT = 8


WampWelcome = list[WAMP_MSG_TYPE, str, int, str]


def wamp_welcome() -> list[WAMP_MSG_TYPE, str, int, str]:
  return [WAMP_MSG_TYPE.WELCOME, 'asdf', 1, 'spacenav-ws']


def wamp_serialize(msg: list[WAMP_MSG_TYPE, str, int, str]) -> str:
  return [int(msg[0])] + msg[1:]


@app.get("/test")
async def get(request: Request):
  return templates.TemplateResponse("test_ws.html", {"request": request})


@app.route("/3dconnexion/nlproxy")
async def nlproxy(request):
  return JSONResponse({"port": "8181"})


class WampProto:

  def __init__(self, socket: WebSocket, stream: asyncio.streams.StreamReader):
    self._socket = socket
    self._data_stream = stream

    self._prefixes = {}
    self._session = None
    self._irpc = {}
    self._orpc = {}
    self._controller = None
    self._view_matrix = None

    self._rpcs = {}

    self._mouse_read = None
    self._ws_read = None
    self._ws_send = None
    self._outgoing = []
    self._subscriptions = set()

  # def _new_session(self) -> str:
  #   sess = ''.join(random.choices(string.ascii_uppercase + string.digits, k=32))
  #   self._session = sess
  #   return sess

  # def welcome(self) -> WampWelcome:
  #   return [WAMP_MSG_TYPE.WELCOME, self._new_session(), 1, 'spacenav-ws']

  # async def prefix(self, alias: str, replace: str):
  #   self._prefixes[replace] = alias

  # async def listen(self):
  #   print('Listening...', flush=True)
  #   msg = await asyncio.wait_for(self._socket.receive_json(), timeout=1.0)
  #   print(f'Received: {msg}', flush=True)
  #   if msg[0] in self._handlers:
  #     print(f'Handling {WAMP_MSG_TYPE(msg[0])}')
  #     await self._handlers[msg[0]](*msg[1:])
  #   else:
  #     print(f'UNKNOWN {WAMP_MSG_TYPE(msg[0])}')

  # def call_result(self, call_id, *results):
  #   self._calls[call_id]['result'] = results
  #   return [WAMP_MSG_TYPE.CALLRESULT, call_id, *results]

  # async def call(self, call_id: str, method: str, *args: list[str]):
  #   print(f'Attempting to call {method} on {call_id}')
  #   self._calls[call_id] = {
  #       'method': method,
  #       'result': None,
  #       'error': None,
  #   }

  #   res = None
  #   if '3dmouse' in args[0]:
  #     print(f'Creating mouse to {method} on {call_id}')
  #     res = self.call_result(call_id, {'connexion': 'mouse0'})
  #   elif '3dcontroller' in args[0]:
  #     print(f'Creating controller to {method} on {call_id}')
  #     self._controller = 'controller0'
  #     res = self.call_result(call_id, {'instance': self._controller})

  #   if res is not None:
  #     print(f'Sending result: {res}')
  #     await self._socket.send_json(res)
  #   print('Done')

  # async def subscribe(self, target: str):
  #   print(f'Subscribed to {target}', flush=True)

  #   if self._view_matrix is None:
  #     print(
  #         'toot',
  #         await self._socket.send_json([
  #             WAMP_MSG_TYPE.EVENT, target,
  #             [WAMP_MSG_TYPE.CALL, 'WAT', 'self:read', 'WAT2', 'view.affine']
  #         ]),
  #         flush=True)
  #     print('Waiting for read...', flush=True)
  #     res = await asyncio.wait_for(self._socket.receive_json(), timeout=1.0)
  #     print(f'Got: {res}', flush=True)
  #     self._view_matrix = np.asarray(res[2]).reshape([4, 4])
  #     print(self._view_matrix, flush=True)
  #   while True:
  #     try:
  #       chunk = await asyncio.wait_for(self._data_stream.read(32), timeout=1.0)
  #     except asyncio.TimeoutError:
  #       print('Timed out waiting for spacemouse, trying again...', flush=True)
  #       continue
  #     message = from_message(unpack("iiiiiiii", chunk))
  #     print(message, flush=True)
  #     assert isinstance(message, MotionEvent)

  #     # fnUpdate - motion

  #     await self._socket.send_json([
  #         WAMP_MSG_TYPE.EVENT, target,
  #         [2, 'WAT', 'self:update', 'WAT2', 'motion',
  #          message.to_3dconn()]
  #     ])

  def _parse_rpc(self, uri: str) -> tuple[str, str]:
    if uri.startswith('http://'):
      return uri.split('#')
    prefix, method = uri.split(':')
    if prefix not in self._prefixes:
      raise ValueError(f'Unknown prefix: {prefix}')
    return self._prefixes[prefix], method

  def resolve(self, uri: str) -> str:
    if ':' not in uri:
      return uri
    prefix, resource = uri.split(':')
    return ''.join([self._prefixes[prefix], resource])

  def prefix(self, short: str, long: str):
    long = long.replace('#', '')
    self._prefixes[short] = long
    print(f'Prefixing "{long}" as "{short}"')

  def call(self, call_id: str, uri: str,
           *args: list[Any]) -> Optional[types.CoroutineType]:
    resource, method = self._parse_rpc(uri)
    print(f'Got RPC: {resource, method}')
    rpcs = self._rpcs.get(resource, None)
    if rpcs is None:
      print(f'Unknown resource type: {resource}')
      # TODO(blakely): handle errors here
      return
    print(f'Looking for RPC handler for {resource}')
    rpc = rpcs.get(method, None)
    if rpc is None:
      print(f'Uknown method for {resource}: {method}')
      # TODO(blakely): handle errors here
      return

    # TODO(blakely): Make these async.
    # rpc_task = asyncio.create_task(rpc(*args))
    # self._irpc[rpc_task] = call_id
    result = rpc(*args)
    return self._socket.send_json([WAMP_MSG_TYPE.CALLRESULT, call_id, result])

  def _rand_id(self, len) -> str:
    return ''.join(
        random.choices(string.ascii_uppercase + string.digits, k=len))

  async def run(self):

    handlers = {
        WAMP_MSG_TYPE.PREFIX: self.prefix,
        WAMP_MSG_TYPE.CALL: self.call,
        WAMP_MSG_TYPE.CALLRESULT: self.result,
        WAMP_MSG_TYPE.SUBSCRIBE: self.subscribe,
    }

    await self._socket.accept(subprotocol="wamp")
    sess = self._rand_id(32)
    self._session = sess
    await self._socket.send_json(
        [WAMP_MSG_TYPE.WELCOME, self._session, 1, 'spacenav-ws'])
    while True:
      print('Listening for events...', flush=True)
      try:
        if self._mouse_read is None:
          self._mouse_read = asyncio.create_task(self._data_stream.read(32))
        if self._ws_read is None:
          self._ws_read = asyncio.create_task(self._socket.receive_json())
        done, _ = await asyncio.wait(
            [self._mouse_read, self._ws_read] + self._outgoing,
            timeout=1.0,
            return_when='FIRST_COMPLETED')
      except asyncio.TimeoutError:
        print('Timed out, trying again...', flush=True)
        continue
      if self._mouse_read in done:
        message = from_message(unpack("iiiiiiii", self._mouse_read.result()))
        print(f'Read mouse: {message}', flush=True)
        self._mouse_read = None
      if self._ws_read in done:
        msg, *payload = self._ws_read.result()
        msg = WAMP_MSG_TYPE(msg)
        print(f'Got message {msg._name_} with payload: {payload}')
        if msg in handlers:
          result = handlers[msg](*payload)
          if result is not None:
            self._outgoing.append(asyncio.create_task(result))
        else:
          print(f'Unhandled message type: {msg._name_}')
        self._ws_read = None
      for task in done:
        if task in self._outgoing:
          self._outgoing.remove(task)

  def subscribe(self, target: str):
    target = self.resolve(target)
    print(f'Subscribed to {target}')
    self._subscriptions.add(target)

    call_id = self._rand_id(16)

    self._orpc[call_id] = self.view_affine

    return self._socket.send_json([
        WAMP_MSG_TYPE.EVENT, target,
        [WAMP_MSG_TYPE.CALL, call_id, 'self:read', 'WAT2', 'view.affine']
    ])

  def view_affine(self, affine_mtx: list[int]):
    print(f'Received affine matrix: {affine_mtx}')

  def result(self, call_id: str, *result):
    print(call_id, result)
    assert call_id in self._orpc
    self._orpc[call_id](*result)

  def registerRPC(self, resource: str, method: str, handler):
    resource_rpcs = self._rpcs.setdefault(resource, {})
    resource_rpcs[method] = handler


@app.websocket("/")
@app.websocket("/3dconnexion")
async def websocket_endpoint(websocket: WebSocket):
  reader, __ = await asyncio.open_unix_connection("/var/run/spnav.sock")

  print('Accepting', flush=True)
  wamp = WampProto(websocket, reader)

  def create(obj: str, *args):
    obj = obj.split(':')[1]
    print(f'Creating {obj} via: {args}')
    if obj.endswith('3dmouse'):
      return {'connexion': 'mouse0'}
    elif obj.endswith('3dcontroller'):
      return {'instance': 'controller0'}
    return {}

  wamp.registerRPC('wss://127.51.68.120/3dconnexion', 'create', create)

  print('Sent', flush=True)

  await wamp.run()


if __name__ == "__main__":
  uvicorn.run(
      "spacenav_ws.main:app",
      host="0.0.0.0",
      port=8000,
      reload=True,
      log_level="debug",
  )
