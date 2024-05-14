import json
import asyncio
from typing_extensions import override
from weakref import WeakValueDictionary
from collections.abc import MutableMapping
from typing import Any, Union, Literal, Optional, overload

from nonebot.utils import escape_tag
from nonebot.exception import WebSocketClosed
from nonebot.compat import type_validate_python
from nonebot.drivers import Driver, Request, WebSocket, HTTPClientMixin, WebSocketClientMixin

from nonebot import get_plugin_config
from nonebot.adapters import Adapter as BaseAdapter

from .bot import Bot
from .model import ModelBase
from .config import Config, ClientInfo
from .event import EVENT_CLASSES, Event
from .utils import API, DatetimeJsonEncoder, log, exclude_none
from .exception import ActionFailed, ApiNotAvailable, RemoteException, code_exceptions_mapping

CallMethod = Literal["get", "post", "multipart"]


class Adapter(BaseAdapter):
    bots: dict[str, Bot]

    @override
    def __init__(self, driver: Driver, **kwargs: Any):
        super().__init__(driver, **kwargs)
        # 读取适配器所需的配置项
        self.mirai_config: Config = get_plugin_config(Config)
        self.tasks: list[asyncio.Task] = []  # 存储 ws 任务
        self.response_waiters: dict[int, MutableMapping[str, asyncio.Future]] = {}
        self.session_keys: dict[int, str] = {}
        self.wss: dict[int, WebSocket] = {}
        self.setup()

    @classmethod
    @override
    def get_name(cls) -> str:
        """适配器名称"""
        return "Mirai"

    def setup(self) -> None:
        if not isinstance(self.driver, HTTPClientMixin):
            # 判断用户配置的Driver类型是否符合适配器要求，不符合时应抛出异常
            raise RuntimeError(
                f"Current driver {self.config.driver} "
                f"doesn't support http client requests!"
                f"{self.get_name()} Adapter need a HTTPClient Driver to work."
            )
        if not isinstance(self.driver, WebSocketClientMixin):
            raise RuntimeError(
                f"Current driver {self.config.driver} does not support "
                "websocket client! "
                f"{self.get_name()} Adapter need a WebSocketClient Driver to work."
            )
        # 在 NoneBot 启动和关闭时进行相关操作
        self.on_ready(self.startup)
        self.driver.on_shutdown(self.shutdown)

    async def startup(self) -> None:
        """定义启动时的操作，例如和平台建立连接"""
        for client in self.mirai_config.mirai_clients:
            self.tasks.append(asyncio.create_task(self.ws(client)))

    async def shutdown(self) -> None:
        for task in self.tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(
            *(asyncio.wait_for(task, timeout=10) for task in self.tasks),
            return_exceptions=True,
        )

    @staticmethod
    @overload
    def validate_response(data: Any, raising: Literal[False]) -> Union[Any, Exception]: ...

    @staticmethod
    @overload
    def validate_response(data: Any, raising: Literal[True] = True) -> Any: ...

    @staticmethod
    def validate_response(data: dict, raising: bool = True):
        int_code = data.get("code") if isinstance(data, dict) else data
        if not isinstance(int_code, int) or int_code == 200 or int_code == 0:
            return data.get("data", data)
        exc_cls = code_exceptions_mapping.get(int_code)
        exc = (
            exc_cls(exc_cls.__doc__ or exc_cls.__name__, int_code, content=str(data))
            if exc_cls
            else RemoteException(RemoteException.__doc__ or "", int_code, content=str(data))
        )
        if raising:
            raise exc
        return exc

    async def ws(self, info: ClientInfo) -> None:
        ws_url = info.ws_url()
        req = Request("GET", ws_url, timeout=60.0)
        while True:
            try:
                async with self.websocket(req) as ws:
                    log(
                        "DEBUG",
                        f"WebSocket Connection to " f"{escape_tag(str(ws_url))} established",
                    )
                    if str(info.account) not in self.bots:
                        bot = Bot(self, info)
                        self.bot_connect(bot)
                        log(
                            "INFO",
                            f"<y>Bot {escape_tag(bot.self_id)}</y> connected",
                        )
                        self.response_waiters.setdefault(info.account, WeakValueDictionary())
                    else:
                        bot = self.bots[str(info.account)]
                    self.wss[info.account] = ws
                    try:
                        await self._loop(info, ws)
                    except WebSocketClosed as e:
                        log(
                            "ERROR",
                            "<r><bg #f8bbd0>WebSocket Closed</bg #f8bbd0></r>",
                            e,
                        )
                    except Exception as e:
                        log(
                            "ERROR",
                            "<r><bg #f8bbd0>Error while process data from websocket "
                            f"{escape_tag(str(ws_url))}. "
                            f"Trying to reconnect...</bg #f8bbd0></r>",
                            e,
                        )
                    finally:
                        self.bot_disconnect(bot)
                        self.wss.pop(info.account, None)
            except Exception as e:
                log(
                    "ERROR",
                    (
                        "<r><bg #f8bbd0>"
                        "Error while setup websocket to "
                        f"{escape_tag(str(ws_url))}. Trying to reconnect..."
                        "</bg #f8bbd0></r>"
                    ),
                    e,
                )
                await asyncio.sleep(5)  # 重连间隔

    async def _loop(self, info: ClientInfo, ws: WebSocket):
        while True:
            data: dict[str, Any] = json.loads(await ws.receive())
            if "code" in data:
                self.validate_response(data)

            sync_id: str = data.get("syncId", "#")
            body: Union[dict, Exception] = self.validate_response(data.get("data"), False)
            if isinstance(body, Exception):
                if sync_id in self.response_waiters[info.account]:
                    self.response_waiters[info.account][sync_id].set_exception(body)
                continue

            if "session" in body:
                self.session_keys[info.account] = body["session"]
                log(
                    "SUCCESS",
                    f"<y>Bot {info.account}</y> session key got.",
                )
                continue

            if sync_id in self.response_waiters[info.account]:
                self.response_waiters[info.account][sync_id].set_result(body)
                continue

            if "type" not in body:
                continue

            event_type = body.pop("type")
            if event_type not in EVENT_CLASSES:
                log(
                    "WARNING",
                    f"received unsupported event <r><bg #f8bbd0>{event_type}</bg #f8bbd0></r>: {body}",
                )
                event = type_validate_python(Event, body)
                event.__event_type__ = event_type  # type: ignore
            else:
                event = type_validate_python(EVENT_CLASSES[event_type], body)
            bot = self.bots[str(info.account)]
            asyncio.create_task(bot.handle_event(event))

    @override
    async def _call_api(self, bot: Bot, api: str, **data: Any) -> Any:
        log("DEBUG", f"Bot {bot.self_id} calling API <y>{api}</y>")
        api_handler: Optional[API] = getattr(bot.__class__, api, None)
        if api_handler is None:
            raise ApiNotAvailable(api)
        return await api_handler(bot, **data)

    async def call(
        self, bot: Bot, action: str, method: CallMethod, params: Optional[dict] = None, session: bool = True
    ) -> dict:
        if bot.info.only_ws:
            return await self._call_ws(bot, action, method, params, session=session)
        return await self._call_http(bot, action, method, params, session=session)

    async def _call_ws(
        self,
        bot: Bot,
        action: str,
        method: CallMethod,
        params: Optional[dict] = None,
        *,
        session: bool = True,
    ) -> dict:
        if not (ws := self.wss.get(bot.info.account)):
            raise RuntimeError("connection is not established")
        if session and not self.session_keys.get(bot.info.account):
            raise RuntimeError("No session key available.")

        if method == "multipart":
            return await self._call_http(bot, action, method, params)

        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        echo = str(hash(future))
        self.response_waiters[bot.info.account][echo] = future
        data = {
            "subCommand": {
                "fetch": "get",
                "post": "update",
            }.get(method)
            or method,
            "syncId": echo,
            "command": action,
            "content": params or {},
            **({"sessionKey": self.session_keys[bot.info.account]} if session else {}),
        }
        try:
            await ws.send(json.dumps(data, cls=DatetimeJsonEncoder))
            return await future
        finally:
            del self.response_waiters[bot.info.account][echo]

    async def _call_http(
        self,
        bot: Bot,
        action: str,
        method: CallMethod,
        params: Optional[dict] = None,
        *,
        session: bool = True,
    ) -> dict:
        if session and not self.session_keys.get(bot.info.account):
            raise RuntimeError("No session key available.")
        action = action.replace("_", "/")
        data = exclude_none(params or {})
        data = {k: v.dict_() if isinstance(v, ModelBase) else v for k, v in data.items()}
        if session:
            data["sessionKey"] = self.session_keys[bot.info.account]
        if method == "get":
            req = Request(
                "GET",
                bot.info.get_url(action),
                params=data,  # type: ignore
            )
        elif method == "post":
            req = Request(
                "POST",
                bot.info.get_url(action),
                json=data,
            )
        else:
            if params is None:
                raise TypeError("multipart requires params")
            files = {}
            for k, v in data.items():
                if isinstance(v, dict):
                    files[k] = (
                        v.get("filename"),
                        v["value"],
                        v.get("content_type"),
                    )
                elif isinstance(v, list):
                    files[k] = (None, json.dumps(v).encode("utf-8"), "application/json")
                else:
                    files[k] = (None, v, None)
            req = Request(
                "POST",
                bot.info.get_url(action),
                files=files,
            )

        try:
            response = await self.request(req)
        except Exception as e:
            raise RemoteException(repr(e), 500) from e
        if not response.content:
            raise ActionFailed("Empty response", response.status_code, response.headers, response.content)
        try:
            data = json.loads(response.content)
        except Exception:
            raise ActionFailed("Invalid response", response.status_code, response.headers, response.content)
        return self.validate_response(data)
