import abc
import dataclasses
import enum
import json
import logging
import random
import string
from typing import Any, Union

import fastapi


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


class WampMessage(abc.ABC):
  ID: WAMP_MSG_TYPE

  def serialize(self) -> list[Any]:
    # aspdifjasoidj
    pass


@dataclasses.dataclass
class Welcome(WampMessage):
  ID = WAMP_MSG_TYPE.WELCOME
  session_id: str
  version: int
  server_ident: str

  def serialize(self):
    return [self.session_id, self.version, self.server_ident]


@dataclasses.dataclass
class Prefix(WampMessage):
  ID = WAMP_MSG_TYPE.PREFIX

  prefix: str
  uri: str

  def serialize(self):
    return [self.prefix, self.uri]


@dataclasses.dataclass
class Call(WampMessage):
  ID = WAMP_MSG_TYPE.CALL

  call_id: str
  proc_uri: str
  args: list[Any]

  def __init__(self, call_id, proc_uri: str, *args, **kwargs):
    self.call_id = call_id
    self.proc_uri = proc_uri
    self.args = args

  def serialize(self):
    return [self.call_id, self.proc_uri, *args]


@dataclasses.dataclass
class CallResult(WampMessage):
  ID = WAMP_MSG_TYPE.CALLRESULT

  call_id: str
  result: Any

  def serialize(self):
    return [self.call_id, self.result]


@dataclasses.dataclass
class CallError(WampMessage):
  ID = WAMP_MSG_TYPE.CALLERROR

  call_id: str
  error_uri: str
  error_desc: str

  def serialize(self):
    return [self.call_id, self.error_uri, self.error_desc]


@dataclasses.dataclass
class Subscribe(WampMessage):
  ID = WAMP_MSG_TYPE.SUBSCRIBE

  topic_uri: str

  def serialize(self):
    return [self.topic_uri]


@dataclasses.dataclass
class Event(WampMessage):
  ID = WAMP_MSG_TYPE.EVENT

  topic_uri: str
  event: Any

  def serialize(self):
    return [self.topic_uri, self.event]


WAMP_TYPES = {
    WAMP_MSG_TYPE.WELCOME: Welcome,
    WAMP_MSG_TYPE.PREFIX: Prefix,
    WAMP_MSG_TYPE.CALL: Call,
    WAMP_MSG_TYPE.CALLRESULT: CallResult,
    WAMP_MSG_TYPE.CALLERROR: CallError,
    WAMP_MSG_TYPE.SUBSCRIBE: Subscribe,
    WAMP_MSG_TYPE.EVENT: Event,
}


def _rand_id(len) -> str:
  return ''.join(random.choices(string.ascii_uppercase + string.digits, k=len))


class WampSession:

  def __init__(self, websocket: fastapi.WebSocket, id_length=16):
    self._socket = websocket
    self._server_id = 'spacenav-ws v0.0.1'
    self._session_id = _rand_id(id_length)

    self._prefixes = {}

    self._msg_handlers = {
        WAMP_MSG_TYPE.PREFIX: self.prefix,
    }

  async def begin(self):
    await self._socket.accept(subprotocol="wamp")
    await self.send_message(Welcome(self._session_id, 1, self._server_id))

  def parse_message(self, msg: Union[str, list[Union[int,
                                                     Any]]]) -> WampMessage:
    if isinstance(msg, str):
      msg: list[Union[int, Any]] = json.loads(msg)

    msg_id, *args = msg
    ctor = WAMP_TYPES.get(msg_id, None)
    if ctor is None:
      raise ValueError(f'Unknown message type: {msg_id}')
    return ctor(*args)

  async def send_message(self, message: WampMessage):
    serialized = [message.ID] + message.serialize()
    await self._socket.send_json(serialized)

  async def process_message(self):
    msg = self.parse_message(await self._socket.receive_json())
    print(msg, flush=True)
    handler = self._msg_handlers.get(msg.ID, None)
    if handler is None:
      logging.warn('Unhandled message type: %s', msg.ID)
      return
    await handler(msg)

  async def prefix(self, msg: Prefix):
    self._prefixes[msg.prefix] = msg.uri