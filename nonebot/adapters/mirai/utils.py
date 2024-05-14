import json
from datetime import datetime
from functools import partial
from collections.abc import Awaitable, Generator
from typing_extensions import ParamSpec, Concatenate
from typing import TYPE_CHECKING, Any, Generic, TypeVar, Callable, Optional, overload

from nonebot.utils import logger_wrapper

if TYPE_CHECKING:
    from .bot import Bot

T = TypeVar("T")
B = TypeVar("B", bound="Bot")
R = TypeVar("R")
P = ParamSpec("P")
log = logger_wrapper("Mirai")


class API(Generic[B, P, R]):
    def __init__(self, func: Callable[Concatenate[B, P], Awaitable[R]]) -> None:
        self.func = func

    def __set_name__(self, owner: type[B], name: str) -> None:
        self.name = name

    @overload
    def __get__(self, obj: None, objtype: type[B]) -> "API[B, P, R]": ...

    @overload
    def __get__(self, obj: B, objtype: Optional[type[B]]) -> Callable[P, Awaitable[R]]: ...

    def __get__(
        self, obj: Optional[B], objtype: Optional[type[B]] = None
    ) -> "API[B, P, R] | Callable[P, Awaitable[R]]":
        if obj is None:
            return self

        return partial(obj.call_api, self.name)  # type: ignore

    async def __call__(self, inst: B, *args: P.args, **kwds: P.kwargs) -> R:
        return await self.func(inst, *args, **kwds)


def gen_subclass(cls: type[T]) -> Generator[type[T], None, None]:
    """生成某个类的所有子类 (包括其自身)

    Args:
        cls (Type[T]): 类

    Yields:
        Type[T]: 子类
    """
    yield cls
    for sub_cls in cls.__subclasses__():
        if TYPE_CHECKING:
            assert issubclass(sub_cls, cls)
        yield from gen_subclass(sub_cls)


class DatetimeJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return int(obj.timestamp())
        return json.JSONEncoder.default(self, obj)


def exclude_none(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def camel_to_snake(name: str) -> str:
    """将 camelCase 字符串转换为 snake_case 字符串"""
    if "_" in name:
        return name
    import re

    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", name)
    name = name.replace("-", "_").lower()
    return name


def snake_to_camel(name: str, capital: bool = False) -> str:
    """将 snake_case 字符串转换为 camelCase 字符串"""
    name = "".join(seg.capitalize() for seg in name.split("_"))
    if not capital:
        name = name[0].lower() + name[1:]
    return name
