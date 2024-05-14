import re
from typing_extensions import override
from typing import TYPE_CHECKING, Union, Optional, overload

from nonebot.message import handle_event
from nonebot.compat import type_validate_python

from nonebot.adapters import Bot as BaseBot

from .utils import API, log
from .config import ClientInfo
from .model import Group, Friend, Member
from .message import Message, MessageSegment
from .event import (
    Event,
    NudgeEvent,
    MemberEvent,
    TempMessage,
    GroupMessage,
    MessageEvent,
    ActiveMessage,
    FriendMessage,
    ActiveTempMessage,
    ActiveGroupMessage,
    ActiveFriendMessage,
)

if TYPE_CHECKING:
    from .adapter import Adapter


def _check_reply(
    bot: "Bot",
    event: MessageEvent,
) -> None:
    """检查消息中存在的回复，赋值 `event.to_me`。

    参数:
        bot: Bot 对象
        event: MessageEvent 对象
    """
    if not event.reply:
        return
    if event.reply.sender == int(bot.self_id):
        event.to_me = True
    message = event.get_message()
    if message and message[0].type == "at" and message[0].data.get("target") == int(bot.self_id):
        event.to_me = True
        del message[0]
    if message and message[0].type == "text":
        message[0].data["text"] = message[0].data["text"].lstrip()
        if not message[0].data["text"]:
            del message[0]
    if not message:
        message.append(MessageSegment.text(""))


def _check_at_me(
    bot: "Bot",
    event: MessageEvent,
):
    def _is_at_me_seg(segment: MessageSegment) -> bool:
        return segment.type == "at" and segment.data.get("target") == int(bot.self_id)

    message = event.get_message()

    # ensure message is not empty
    if not message:
        message.append(MessageSegment.text(""))

    deleted = False
    if _is_at_me_seg(message[0]):
        message.pop(0)
        event.to_me = True
        deleted = True
        if message and message[0].type == "text":
            message[0].data["text"] = message[0].data["text"].lstrip("\xa0").lstrip()
            if not message[0].data["text"]:
                del message[0]

    if not deleted:
        # check the last segment
        i = -1
        last_msg_seg = message[i]
        if last_msg_seg.type == "text" and not last_msg_seg.data["text"].strip() and len(message) >= 2:
            i -= 1
            last_msg_seg = message[i]

        if _is_at_me_seg(last_msg_seg):
            event.to_me = True
            del message[i:]

    if not message:
        message.append(MessageSegment.text(""))


def _check_nickname(bot: "Bot", event: MessageEvent) -> None:
    """检查消息开头是否存在昵称，去除并赋值 `event.to_me`。

    参数:
        bot: Bot 对象
        event: MessageEvent 对象
    """
    message = event.get_message()
    first_msg_seg = message[0]
    if first_msg_seg.type != "text":
        return

    nicknames = {re.escape(n) for n in bot.config.nickname}
    if not nicknames:
        return

    # check if the user is calling me with my nickname
    nickname_regex = "|".join(nicknames)
    first_text = first_msg_seg.data["text"]
    if m := re.search(rf"^({nickname_regex})([\s,，]*|$)", first_text, re.IGNORECASE):
        log("DEBUG", f"User is calling me {m[1]}")
        event.to_me = True
        first_msg_seg.data["text"] = first_text[m.end() :]


class Bot(BaseBot):
    adapter: "Adapter"

    @override
    def __init__(self, adapter: "Adapter", info: ClientInfo):
        super().__init__(adapter, str(info.account))

        # Bot 配置信息
        self.info: ClientInfo = info

    def __getattr__(self, item):
        raise AttributeError(f"'Bot' object has no attribute '{item}'")

    async def handle_event(self, event: Event) -> None:
        if isinstance(event, MessageEvent):
            _check_reply(self, event)
            _check_at_me(self, event)
            _check_nickname(self, event)
        await handle_event(self, event)

    @override
    async def send(
        self,
        event: Event,
        message: Union[str, Message, MessageSegment],
        **kwargs,
    ) -> ActiveMessage:
        if isinstance(event, MessageEvent):
            return await self.send_message(event, message, **kwargs)
        if isinstance(event, FriendMessage):
            return await self.send_message(event.sender, message, **kwargs)
        if isinstance(event, (GroupMessage, MemberEvent)):
            return await self.send_message(event.group, message, **kwargs)
        if isinstance(event, NudgeEvent):
            return await self.send_message(event.subject, message, **kwargs)  # type: ignore
        else:
            raise TypeError(event)

    @overload
    async def send_message(
        self,
        target: MessageEvent,
        message: Union[str, Message, MessageSegment],
        quote: Optional[bool] = None,
    ) -> ActiveMessage: ...

    @overload
    async def send_message(
        self,
        target: Union[Group, Friend, Member],
        message: Union[str, Message, MessageSegment],
        quote: Optional[int] = None,
    ) -> ActiveMessage: ...

    async def send_message(
        self,
        target: Union[MessageEvent, Group, Friend, Member],
        message: Union[str, Message, MessageSegment],
        quote: Union[bool, int, None] = None,
    ) -> ActiveMessage:
        """发送消息

        Args:
            target (Union[MessageEvent, Group, Friend, Member]): 消息发送目标.
            message (Union[str, Message, MessageSegment]): 要发送的消息.
            quote (Union[bool, int, None], optional): 若为布尔类型, 则会尝试通过传入对象解析要回复的消息, \
            否则会视为 `messageId` 处理.

        Returns:
            ActiveMessage: Bot 主动消息对象
        """
        _message = Message(message)
        _quote = None
        if isinstance(quote, bool):
            if quote:
                if isinstance(target, MessageEvent):
                    _quote = target.message_id
                else:
                    raise TypeError("Passing `quote=True` is only valid when passing a MessageEvent.")
        elif isinstance(quote, int):
            _quote = quote
        elif _message.has("$mirai:reply"):
            _quote = _message.get("$mirai:reply")[0].data["id"]
            _message = _message.exclude("$mirai:reply")
        params: dict = {
            "message": _message,
            "quote": _quote,
        }
        if isinstance(target, GroupMessage):
            params["target"] = target.sender.group
        elif isinstance(target, (FriendMessage, TempMessage)):
            params["target"] = target.sender
        else:  # target: sender
            params["target"] = target
        if isinstance(params["target"], Friend):
            result = await self.send_friend_message(**params)
        elif isinstance(params["target"], Group):
            result = await self.send_group_message(**params)
        elif isinstance(params["target"], Member):
            result = await self.send_temp_message(**params)
        else:
            raise ValueError("Invalid target")
        return result

    @API
    async def send_friend_message(
        self,
        *,
        target: Union[Friend, int],
        message: Union[str, Message, MessageSegment],
        quote: Optional[int] = None,
    ) -> ActiveFriendMessage:
        """发送消息给好友, 可以指定回复的消息.

        Args:
            target (Union[Friend, int]): 指定的好友
            message (Union[str, Message, MessageSegment]): 要发送的消息.
            quote (Optional[int], optional): 需要回复的消息, 默认为 None.

        Returns:
            ActiveFriendMessage: 即当前会话账号所发出消息的事件, 可用于回复.
        """

        _message = Message(message)
        _quote = quote
        if _message.has("$mirai:reply"):
            _quote = _message.get("$mirai:reply")[0].data["id"]
            _message = _message.exclude("$mirai:reply")
        _message = _message.exclude("source", "quote")

        result = await self.adapter.call(
            self,
            "sendFriendMessage",
            "post",
            {
                "target": int(target),
                "messageChain": _message.to_elements(),
                **({"quote": _quote} if _quote else {}),
            },
        )
        return type_validate_python(
            ActiveFriendMessage,
            {
                "messageChain": message,
                "message_id": result["messageId"],
                "subject": target if isinstance(target, Friend) else await self.get_friend(target=target),
            },
        )

    @API
    async def send_group_message(
        self,
        *,
        target: Union[Group, Member, int],
        message: Union[str, Message, MessageSegment],
        quote: Optional[int] = None,
    ) -> ActiveGroupMessage:
        """发送消息到群组内, 可以指定回复的消息.

        Args:
            target (Union[Group, Member, int]): 指定的群组, 可以是群组的 ID 也可以是 Group 或 Member 实例.
            message (Union[str, Message, MessageSegment]): 要发送的消息.
            quote (Optional[int], optional): 需要回复的消息, 默认为 None.

        Returns:
            ActiveGroupMessage: 即当前会话账号所发出消息的事件, 可用于回复.
        """
        _message = Message(message)
        _quote = quote
        if _message.has("$mirai:reply"):
            _quote = _message.get("$mirai:reply")[0].data["id"]
            _message = _message.exclude("$mirai:reply")
        _message = _message.exclude("source", "quote")

        if isinstance(target, Member):
            target = target.group

        result = await self.adapter.call(
            self,
            "sendGroupMessage",
            "post",
            {
                "target": int(target),
                "messageChain": _message.to_elements(),
                **({"quote": _quote} if _quote else {}),
            },
        )
        return type_validate_python(
            ActiveGroupMessage,
            {
                "messageChain": message,
                "message_id": result["messageId"],
                "subject": target if isinstance(target, Group) else await self.get_group(target=int(target)),
            },
        )

    @API
    async def send_temp_message(
        self,
        *,
        target: Union[Member, int],
        message: Union[str, Message, MessageSegment],
        group: Optional[Union[Group, int]] = None,
        quote: Optional[int] = None,
    ) -> ActiveTempMessage:
        """发送临时会话给群组中的特定成员, 可指定回复的消息.

        Warning:
            本 API 大概率会导致账号风控/冻结. 请谨慎使用.

        Args:
            group (Union[Group, int]): 指定的群组, 可以是群组的 ID 也可以是 Group 实例.
            target (Union[Member, int]): 指定的群组成员, 可以是成员的 ID 也可以是 Member 实例.
            message (Union[str, Message, MessageSegment]): 要发送的消息.
            quote (Optional[int], optional): 需要回复的消息, 默认为 None.

        Returns:
            ActiveTempMessage: 即当前会话账号所发出消息的事件, 可用于回复.
        """
        _message = Message(message)
        _quote = quote
        if _message.has("$mirai:reply"):
            _quote = _message.get("$mirai:reply")[0].data["id"]
            _message = _message.exclude("$mirai:reply")
        _message = _message.exclude("source", "quote")
        group = target.group if (isinstance(target, Member) and not group) else group
        if not group:
            raise ValueError("Missing necessary argument: group")

        result = await self.adapter.call(
            self,
            "sendTempMessage",
            "post",
            {
                "group": int(group),
                "qq": int(target),
                "messageChain": _message.to_elements(),
                **({"quote": _quote} if _quote else {}),
            },
        )
        return type_validate_python(
            ActiveTempMessage,
            {
                "messageChain": message,
                "message_id": result["messageId"],
                "subject": (
                    target
                    if isinstance(target, Member)
                    else await self.get_member(group=int(group), target=int(target))
                ),
            },
        )

    @API
    async def get_friend(self, *, target: int) -> Friend: ...

    @API
    async def get_group(self, *, target: int) -> Group: ...

    @API
    async def get_member(self, *, group: int, target: int) -> Member: ...
