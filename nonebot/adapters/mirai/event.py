"""Ariadne 的事件"""

from enum import Enum
from copy import deepcopy
from datetime import datetime
from typing_extensions import override, deprecated
from typing import TYPE_CHECKING, Any, Union, Literal, TypeVar, Optional

from pydantic import Field
from nonebot.internal.matcher import current_bot
from nonebot.internal.adapter import Event as BaseEvent

from .compat import model_validator
from .message import Quote, Source, Message
from .model import Group, Friend, Member, Stranger, ModelBase, MemberPerm, OtherClient


class Event(BaseEvent, ModelBase):
    """Mirai 的事件基类"""

    __event_type__: str
    """事件类型"""

    def get_type(self) -> str:
        return ""

    def get_event_name(self) -> str:
        return self.__event_type__

    def get_event_description(self) -> str:
        return self.__event_type__

    def get_user_id(self) -> str:
        raise ValueError("This event does not have a user_id")

    def get_session_id(self) -> str:
        raise ValueError("This event does not have a session_id")

    def get_message(self) -> "Message":
        raise ValueError("This event does not have a message")

    def is_tome(self) -> bool:
        return False


EVENT_CLASSES: dict[str, type[Event]] = {}

E = TypeVar("E", bound="Event")


def register_event_class(event_class: type[E]) -> type[E]:
    EVENT_CLASSES[event_class.__event_type__] = event_class
    return event_class


class Reply(ModelBase):
    id: int
    group: int
    sender: int
    target: int
    origin: Message


def generate_message(_, values: dict[str, Any]):
    chain: list[dict[str, Any]] = values["messageChain"]
    removed = set()
    for index, element in enumerate(chain[:2]):
        if isinstance(element, Source):
            values["message_id"] = element.data["id"]
            values["time"] = (
                datetime.fromtimestamp(element.data["time"]) if element.data["time"] else datetime.now()
            )
            removed.add(index)
        elif isinstance(element, Quote):
            values["reply"] = Reply(
                id=element.data["id"],
                group=element.data["groupId"],
                sender=element.data["senderId"],
                target=element.data["targetId"],
                origin=Message.from_elements(element.data["origin"]),
            )
            removed.add(index)
        elif isinstance(element, dict):
            if element.get("type", "Unknown") == "Source":
                values["message_id"] = element["id"]
                values["time"] = (
                    datetime.fromtimestamp(element["time"]) if element.get("time") else datetime.now()
                )
                removed.add(index)
            elif element.get("type", "Unknown") == "Quote":
                values["reply"] = Reply(
                    id=element["id"],
                    group=element["groupId"],
                    sender=element["senderId"],
                    target=element["targetId"],
                    origin=Message.from_elements(element["origin"]),
                )
                removed.add(index)
    values["messageChain"] = [element for index, element in enumerate(chain) if index not in removed]
    values["message"] = Message.from_elements(values["messageChain"])
    values["original_message"] = deepcopy(values["message"])
    return values


class MessageEvent(Event):
    """消息事件基类"""

    raw_message: list[dict] = Field(..., alias="messageChain")
    """消息链"""

    sender: Union[Friend, Member, OtherClient, Stranger]
    """发送者"""

    message_id: int = Field(-1)
    """消息 ID"""

    time: datetime = Field(default_factory=datetime.now)
    """消息发送时间"""

    reply: Optional[Reply] = None
    """可能的引用消息对象"""

    to_me: bool = False

    if TYPE_CHECKING:
        message: Message
        original_message: Message

    __setter = model_validator(mode="before")(generate_message)

    def __int__(self):
        return self.message_id

    @override
    def get_type(self) -> str:
        return "message"

    @override
    def is_tome(self) -> bool:
        return self.to_me

    @override
    def get_message(self) -> Message:
        return self.message

    @override
    def get_user_id(self) -> str:
        return str(self.sender.id)

    @override
    def get_session_id(self) -> str:
        return str(self.sender.id)


@register_event_class
class FriendMessage(MessageEvent):
    """好友消息事件"""

    __event_type__ = "FriendMessage"

    sender: Friend


@register_event_class
class GroupMessage(MessageEvent):
    """群消息事件"""

    __event_type__ = "GroupMessage"

    sender: Member

    group: Group

    @model_validator(mode="before")
    def get_group(cls, values: dict[str, Any]):
        values["group"] = values["sender"]["group"]
        return values

    @override
    def get_session_id(self) -> str:
        return f"{self.group.id}_{self.sender.id}"


@register_event_class
class TempMessage(MessageEvent):
    """临时消息事件"""

    __event_type__ = "TempMessage"

    sender: Member

    group: Group

    @model_validator(mode="before")
    def get_group(cls, values: dict[str, Any]):
        values["group"] = values["sender"]["group"]
        return values

    @override
    def get_session_id(self) -> str:
        return f"{self.group.id}_{self.sender.id}"


@register_event_class
class StrangerMessage(MessageEvent):
    """陌生人消息事件"""

    __event_type__ = "StrangerMessage"

    sender: Stranger


@register_event_class
class OtherClientMessage(MessageEvent):
    """其他客户端消息事件"""

    __event_type__ = "OtherClientMessage"

    sender: OtherClient


class ActiveMessage(Event):
    """主动消息：Bot 账号发送给他人的消息"""

    raw_message: list[dict] = Field(..., alias="messageChain")
    """消息链"""

    subject: Union[Friend, Group, Member, Stranger]
    """消息接收者"""

    sync: bool = False
    """是否为同步消息"""

    message_id: int = Field(-1)
    """消息 ID"""

    time: datetime = Field(default_factory=datetime.now)
    """消息发送时间"""

    reply: Optional[Reply] = None
    """可能的引用消息对象"""

    if TYPE_CHECKING:
        message: Message
        original_message: Message

    __setter = model_validator(mode="before")(generate_message)

    def __int__(self):
        return self.message_id

    @override
    def get_type(self) -> str:
        return "message"

    @override
    def is_tome(self) -> bool:
        return True

    @override
    def get_message(self) -> Message:
        return self.message

    @override
    def get_user_id(self) -> str:
        return str(self.subject.id)

    @override
    def get_session_id(self) -> str:
        return str(self.subject.id)


@register_event_class
class ActiveFriendMessage(ActiveMessage):
    """主动好友消息事件"""

    __event_type__ = "ActiveFriendMessage"

    subject: Friend


@register_event_class
class ActiveGroupMessage(ActiveMessage):
    """主动群消息事件"""

    __event_type__ = "ActiveGroupMessage"

    subject: Group


@register_event_class
class ActiveTempMessage(ActiveMessage):
    """主动临时消息事件"""

    __event_type__ = "ActiveTempMessage"

    subject: Member


@register_event_class
class ActiveStrangerMessage(ActiveMessage):
    """主动陌生人消息事件"""

    __event_type__ = "ActiveStrangerMessage"

    subject: Stranger


class SyncMessage(ActiveMessage):
    """同步消息：从其他客户端同步的主动消息"""

    sync: bool = True
    """是否为同步消息"""


@register_event_class
class FriendSyncMessage(SyncMessage, ActiveFriendMessage):
    """好友同步消息事件"""

    __event_type__ = "FriendSyncMessage"


@register_event_class
class GroupSyncMessage(SyncMessage, ActiveGroupMessage):
    """群同步消息事件"""

    __event_type__ = "GroupSyncMessage"


@register_event_class
class TempSyncMessage(SyncMessage, ActiveTempMessage):
    """临时同步消息事件"""

    __event_type__ = "TempSyncMessage"


@register_event_class
class StrangerSyncMessage(SyncMessage, ActiveStrangerMessage):
    """陌生人同步消息事件"""

    __event_type__ = "StrangerSyncMessage"


class NoticeEvent(Event):
    @override
    def get_type(self) -> str:
        return "notice"


class BotEvent(NoticeEvent):
    """指示有关 Bot 本身的事件."""


class FriendEvent(NoticeEvent):
    """指示有关好友的事件"""

    friend: Friend

    @override
    def get_user_id(self) -> str:
        return str(self.friend.id)

    @override
    def get_session_id(self) -> str:
        return str(self.friend.id)


class GroupEvent(NoticeEvent):
    """指示有关群组的事件."""

    group: Group


class MemberEvent(GroupEvent):
    """指示有关群组成员的事件."""

    member: Member

    @override
    def get_user_id(self) -> str:
        return str(self.member.id)

    @override
    def get_session_id(self) -> str:
        return f"{self.group.id}_{self.member.id}"

    @model_validator(mode="before")
    def get_group(cls, values: dict[str, Any]):
        if "group" not in values:
            values["group"] = values["member"]["group"]
        return values


@register_event_class
class BotOnlineEvent(BotEvent):
    """Bot 账号登录成功

    Note: 提示
        只有使用 ReverseAdapter 时才有可能接受到此事件
    """

    __event_type__ = "BotOnlineEvent"

    qq: int
    """登录成功的 Bot 的 QQ 号"""


@register_event_class
class BotOfflineEventActive(BotEvent):
    """Bot 账号主动离线"""

    __event_type__ = "BotOfflineEventActive"

    qq: int
    """主动离线的 Bot 的 QQ 号"""


@register_event_class
class BotOfflineEventForce(BotEvent):
    """Bot 账号被迫下线"""

    __event_type__ = "BotOfflineEventForce"

    qq: int
    """被迫下线的 Bot 的 QQ 号"""


@register_event_class
class BotOfflineEventDropped(BotEvent):
    """Bot 账号被服务器断开连接"""

    __event_type__ = "BotOfflineEventDropped"

    qq: int
    """被断开连接的 Bot 的 QQ 号"""


@register_event_class
class BotReloginEvent(BotEvent):
    """Bot 账号重新登录"""

    __event_type__ = "BotReloginEvent"

    qq: int
    """重新登录的 Bot 的 QQ 号"""


@register_event_class
class BotGroupPermissionChangeEvent(GroupEvent, BotEvent):
    """Bot 账号在一特定群组内所具有的权限发生变化"""

    __event_type__ = "BotGroupPermissionChangeEvent"

    origin: MemberPerm
    """原始权限"""

    current: MemberPerm
    """当前权限"""


@register_event_class
class BotMuteEvent(GroupEvent, BotEvent):
    """Bot 账号在一特定群组内被管理员/群主禁言"""

    __event_type__ = "BotMuteEvent"

    duration: int = Field(..., alias="durationSeconds")
    """禁言时长, 单位为秒"""

    operator: Member
    """执行禁言操作的管理员/群主"""

    @model_validator(mode="before")
    def get_group(cls, values: dict[str, Any]):
        values["group"] = values["operator"]["group"]
        return values


@register_event_class
class BotUnmuteEvent(GroupEvent, BotEvent):
    """Bot 账号在一特定群组内被管理员/群主解除禁言"""

    __event_type__ = "BotUnmuteEvent"

    operator: Member
    """执行解除禁言操作的管理员/群主"""

    @model_validator(mode="before")
    def get_group(cls, values: dict[str, Any]):
        values["group"] = values["operator"]["group"]
        return values


@register_event_class
class BotJoinGroupEvent(GroupEvent, BotEvent):
    """Bot 账号加入了一个新群组"""

    __event_type__ = "BotJoinGroupEvent"

    inviter: Optional[Member] = Field(None, alias="invitor")
    """如果被邀请入群则为邀请人的 Member 对象"""


@register_event_class
class BotLeaveEventActive(GroupEvent, BotEvent):
    """Bot 账号主动退出了某群组."""

    __event_type__ = "BotLeaveEventActive"


@register_event_class
class BotLeaveEventKick(GroupEvent, BotEvent):
    """Bot 账号被管理员/群主踢出了某群组"""

    __event_type__ = "BotLeaveEventKick"

    operator: Optional[Member] = None
    """操作员, 为群主或管理员"""


@register_event_class
class BotLeaveEventDisband(GroupEvent, BotEvent):
    """Bot 账号所在的某群组被解散"""

    __event_type__ = "BotLeaveEventDisband"

    operator: Optional[Member] = None
    """操作员, 为群主"""


@register_event_class
class FriendAddEvent(FriendEvent):
    """有一位新用户添加了 Bot 账号为好友"""

    __event_type__ = "FriendAddEvent"

    stranger: bool
    """是否为陌生人添加

    若为 true 对应为 StrangerRelationChangeEvent.Friended 的 mirai 事件

    否则为 FriendAddEvent
    """


@register_event_class
class FriendDeleteEvent(FriendEvent):
    """有一位用户删除了 Bot 账号好友关系"""

    __event_type__ = "FriendDeleteEvent"


@register_event_class
class FriendInputStatusChangedEvent(FriendEvent):
    """好友输入状态改变"""

    __event_type__ = "FriendInputStatusChangedEvent"

    inputting: bool
    """好友是否正在输入"""


@register_event_class
class FriendNickChangedEvent(FriendEvent):
    """好友消息撤回"""

    __event_type__ = "FriendNickChangedEvent"

    old_name: str = Field(..., alias="from")
    """原昵称"""

    new_name: str = Field(..., alias="to")
    """新昵称"""


@register_event_class
class FriendRecallEvent(FriendEvent):
    """有一位与 Bot 账号为好友关系的用户撤回了一条消息"""

    __event_type__ = "FriendRecallEvent"

    author_id: int = Field(..., alias="authorId")
    """原消息发送者的 QQ 号"""

    message_id: int = Field(..., alias="messageId")
    """原消息的 ID"""

    time: datetime
    """原消息发送时间"""

    operator: int
    """撤回消息者的 QQ 号"""

    @model_validator(mode="before")
    def get_friend(cls, values):
        values["friend"] = {"id": values["authorId"], "nickname": "", "remark": ""}
        return values

    @override
    def get_user_id(self) -> str:
        return str(self.author_id)

    @override
    def get_session_id(self) -> str:
        return str(self.author_id)


@register_event_class
class GroupRecallEvent(GroupEvent):
    """有群成员在指定群组撤回了一条消息。
    群成员若具有管理员/群主权限,
    则他们可以撤回其他普通群员的消息, 且不受发出时间限制。
    """

    __event_type__ = "GroupRecallEvent"

    author_id: int = Field(..., alias="authorId")
    """原消息发送者的 QQ 号"""

    message_id: int = Field(..., alias="messageId")
    """原消息的 ID"""

    time: datetime
    """原消息发送时间"""

    operator: Optional[Member] = None
    """撤回消息的群成员, 若为 None 则为 Bot 账号操作"""

    @override
    def get_user_id(self) -> str:
        return str(self.author_id)

    @override
    def get_session_id(self) -> str:
        return f"{self.group.id}_{self.author_id}"


class NudgeEvent(NoticeEvent):
    """Bot 账号被某个账号在相应上下文区域进行 "双击头像"(Nudge) 的行为.

    请与 '戳一戳(Poke)' 区分开来，后者属于一种消息元素，而非专门的动作。
    """

    __event_type__ = "NudgeEvent"

    supplicant: int = Field(..., alias="fromId")
    """动作发出者的 QQ 号"""

    target: int
    """动作目标的 QQ 号"""

    msg_action: str = Field(..., alias="action")
    """动作类型"""

    msg_suffix: str = Field(..., alias="suffix")
    """自定义动作内容"""

    subject: Union[Group, Friend, Stranger, OtherClient, dict[str, Any]] = Field(...)
    """事件来源上下文"""

    @property
    def scene(self) -> Literal["group", "friend", "stranger", "client"]:
        """双击头像的发生场景"""
        if isinstance(self.subject, Group):
            return "group"
        elif isinstance(self.subject, Friend):
            return "friend"
        elif isinstance(self.subject, Stranger):
            return "stranger"
        elif isinstance(self.subject, OtherClient):
            return "client"
        else:
            return self.subject["kind"]


@register_event_class
class GroupNameChangeEvent(GroupEvent):
    """有一群组被修改了群名称"""

    __event_type__ = "GroupNameChangeEvent"

    origin: str
    """原始设定"""

    current: str
    """当前设定"""

    operator: Optional[Member] = None
    """作出此操作的管理员/群主, 若为 None 则为 Bot 账号操作"""


@register_event_class
class GroupEntranceAnnouncementChangeEvent(GroupEvent):
    """有一群组被修改了入群公告"""

    __event_type__ = "GroupEntranceAnnouncementChangeEvent"

    origin: str
    """原始设定"""

    current: str
    """当前设定"""

    operator: Optional[Member] = None
    """作出此操作的管理员/群主, 若为 None 则为 Bot 账号操作"""


@register_event_class
class GroupMuteAllEvent(GroupEvent):
    """有一群组全体禁言状态发生变化"""

    __event_type__ = "GroupMuteAllEvent"

    origin: bool
    """原始状态"""

    current: bool
    """当前状态"""

    operator: Optional[Member] = None
    """作出此操作的管理员/群主, 若为 None 则为 Bot 账号操作"""


@register_event_class
@deprecated("This event is deprecated that QQ has removed this feature.")
class GroupAllowAnonymousChatEvent(GroupEvent):
    """有一群组匿名聊天状态发生变化"""

    __event_type__ = "GroupAllowAnonymousChatEvent"

    origin: bool
    """原始状态"""

    current: bool
    """当前状态"""

    operator: Optional[Member] = None
    """作出此操作的管理员/群主, 若为 None 则为 Bot 账号操作"""


@register_event_class
@deprecated("This event is deprecated that QQ has removed this feature.")
class GroupAllowConfessTalkEvent(GroupEvent):
    """有一群组坦白说状态发生变化"""

    __event_type__ = "GroupAllowConfessTalkEvent"

    origin: bool
    """原始状态"""

    current: bool
    """当前状态"""

    operator: Optional[Member] = None
    """作出此操作的管理员/群主, 若为 None 则为 Bot 账号操作"""


@register_event_class
class GroupAllowMemberInviteEvent(GroupEvent):
    """有一群组成员邀请状态发生变化"""

    __event_type__ = "GroupAllowMemberInviteEvent"

    origin: bool
    """原始状态"""

    current: bool
    """当前状态"""

    operator: Optional[Member] = None
    """作出此操作的管理员/群主, 若为 None 则为 Bot 账号操作"""


@register_event_class
class MemberJoinEvent(MemberEvent):
    """有一新成员加入了一特定群组"""

    __event_type__ = "MemberJoinEvent"

    inviter: Optional[Member] = Field(None, alias="invitor")
    """邀请该成员的成员, 可为 None"""


@register_event_class
class MemberLeaveEventKick(MemberEvent):
    """有一成员被踢出了一特定群组"""

    __event_type__ = "MemberLeaveEventKick"

    operator: Optional[Member] = None
    """执行踢出操作的管理员/群主, 可为 None"""


@register_event_class
class MemberLeaveEventQuit(MemberEvent):
    """有一成员主动退出了一特定群组"""

    __event_type__ = "MemberLeaveEventQuit"


@register_event_class
class MemberCardChangeEvent(MemberEvent):
    """有一群组成员的群名片被更改。

    执行者可能是管理员/群主, 该成员自己, 也可能是 Bot 账号 (这时 `operator` 为 `None`).
    """

    __event_type__ = "MemberCardChangeEvent"

    origin: str
    """原始群名片"""

    current: str
    """现在的群名片"""

    operator: Optional[Member] = None
    """更改群名片的操作者, 可能是管理员/群主, 该成员自己, 也可能是 Bot 账号(这时, `operator` 为 `None`)."""


@register_event_class
class MemberSpecialTitleChangeEvent(MemberEvent):
    """有一群组成员的专属头衔被更改。执行者只可能是群主"""

    __event_type__ = "MemberSpecialTitleChangeEvent"

    origin: str
    """原始专属头衔"""

    current: str
    """现在的专属头衔"""


@register_event_class
class MemberPermissionChangeEvent(MemberEvent):
    """有一群组成员的权限被更改。执行者只可能是群主"""

    __event_type__ = "MemberPermissionChangeEvent"

    origin: MemberPerm
    """原始权限"""

    current: MemberPerm
    """现在的权限"""


@register_event_class
class MemberMuteEvent(MemberEvent):
    """有一群组成员被禁言, 当 `operator` 为 `None` 时为 Bot 账号操作."""

    __event_type__ = "MemberMuteEvent"

    duration: int = Field(..., alias="durationSeconds")
    """禁言时长, 单位为秒"""

    operator: Optional[Member] = None
    """执行禁言操作的管理员/群主"""


@register_event_class
class MemberUnmuteEvent(MemberEvent):
    """有一群组成员被解除禁言, 当 `operator` 为 `None` 时为 Bot 账号操作."""

    __event_type__ = "MemberUnmuteEvent"

    operator: Optional[Member] = None
    """执行解除禁言操作的管理员/群主"""


@register_event_class
class MemberHonorChangeEvent(MemberEvent):
    """有一群组成员的称号被更改。"""

    __event_type__ = "MemberHonorChangeEvent"

    action: str
    """对应的操作, 可能是 `"achieve"` 或 `"lose"`"""

    honor: str
    """获得/失去的荣誉"""


class RequestEvent(Event):
    request_id: int = Field(..., alias="eventId")
    """事件标识，响应该事件时的标识"""

    supplicant: int = Field(..., alias="fromId")
    """申请人QQ号"""

    nickname: str = Field(..., alias="nick")
    """申请人的昵称或群名片"""

    source_group: int = Field(0, alias="groupId")

    message: str
    """申请消息"""

    @override
    def get_type(self) -> str:
        return "request"

    async def _operate(self, operation: int, msg: str = "") -> None:
        """内部接口, 用于内部便捷发送相应操作."""
        bot = current_bot.get()
        await bot.call_api(
            "operate_request",
            **{
                "event": self,
                "operate": operation,
                "message": msg,
            },
        )


@register_event_class
class NewFriendRequestEvent(RequestEvent):
    """有一用户向机器人提起好友请求.

    事件拓展支持:
        该事件的处理需要你获取原始事件实例.

        1. 同意请求: `await event.accept()`, 具体查看该方法所附带的说明.
        2. 拒绝请求: `await event.reject()`, 具体查看该方法所附带的说明.
        3. 拒绝并不再接受来自对方的请求: `await event.block()`, 具体查看该方法所附带的说明.
    """

    __event_type__ = "FriendRequestEvent"

    async def accept(self, message: str = "") -> None:
        """同意对方的加好友请求.

        Args:
            message (str, optional): 附带给对方的消息. 默认为 "".

        Raises:
            LookupError: 尝试上下文外处理事件.
            InvalidSession: 应用实例没准备好!

        Returns:
            None: 没有返回.
        """
        await self._operate(0, message)

    async def reject(self, message: str = "") -> None:
        """拒绝对方的加好友请求.

        Args:
            message (str, optional): 附带给对方的消息. 默认为 "".

        Raises:
            LookupError: 尝试上下文外处理事件.
            InvalidSession: 应用实例没准备好!

        Returns:
            None: 没有返回.
        """
        await self._operate(1, message)

    async def block(self, message: str = "") -> None:
        """拒绝对方的加好友请求, 并不再接受来自对方的加好友请求.

        Args:
            message (str, optional): 附带给对方的消息. 默认为 "".

        Raises:
            LookupError: 尝试上下文外处理事件.
            InvalidSession: 应用实例没准备好!

        Returns:
            None: 没有返回.
        """
        await self._operate(2, message)


@register_event_class
class MemberJoinRequestEvent(RequestEvent):
    """有一用户向机器人作为管理员/群主的群组申请加入群组.

    事件拓展支持:
        该事件的处理需要你获取原始事件实例.

        1. 同意请求: `await event.accept()`, 具体查看该方法所附带的说明.
        2. 拒绝请求: `await event.reject()`, 具体查看该方法所附带的说明.
        3. 忽略请求: `await event.ignore()`, 具体查看该方法所附带的说明.
        4. 拒绝并不再接受来自对方的请求: `await event.reject_block()`, 具体查看该方法所附带的说明.
        5. 忽略并不再接受来自对方的请求: `await event.ignore_block()`, 具体查看该方法所附带的说明.
    """

    __event_type__ = "MemberJoinRequestEvent"

    group_name: str = Field(..., alias="groupName")
    """申请人申请入群的群名称"""

    inviter_id: Optional[int] = Field(None, alias="invitorId")
    """邀请该申请人的成员QQ号, 可为 None"""

    async def accept(self, message: str = "") -> None:
        """同意对方加入群组.

        Args:
            message (str, optional): 附带给对方的消息. 默认为 "".

        Raises:
            LookupError: 尝试上下文外处理事件.
            InvalidSession: 应用实例没准备好!

        Returns:
            None: 没有返回.
        """
        await self._operate(0, message)

    async def reject(self, message: str = "") -> None:
        """拒绝对方加入群组.

        Args:
            message (str, optional): 附带给对方的消息. 默认为 "".

        Raises:
            LookupError: 尝试上下文外处理事件.
            InvalidSession: 应用实例没准备好!

        Returns:
            None: 没有返回.
        """
        await self._operate(1, message)

    async def ignore(self, message: str = "") -> None:
        """忽略对方加入群组的请求.

        Args:
            message (str, optional): 附带给对方的消息. 默认为 "".

        Raises:
            LookupError: 尝试上下文外处理事件.
            InvalidSession: 应用实例没准备好!

        Returns:
            None: 没有返回.
        """
        await self._operate(2, message)

    async def reject_block(self, message: str = "") -> None:
        """拒绝对方加入群组的请求, 并不再接受来自对方加入群组的请求.

        Args:
            message (str, optional): 附带给对方的消息. 默认为 "".

        Raises:
            LookupError: 尝试上下文外处理事件.
            InvalidSession: 应用实例没准备好!

        Returns:
            None: 没有返回.
        """
        await self._operate(3, message)

    async def ignore_block(self, message: str = "") -> None:
        """忽略对方加入群组的请求, 并不再接受来自对方加入群组的请求.

        Args:
            message (str, optional): 附带给对方的消息. 默认为 "".

        Raises:
            LookupError: 尝试上下文外处理事件.
            InvalidSession: 应用实例没准备好!

        Returns:
            None: 没有返回.
        """
        await self._operate(4, message)


@register_event_class
class BotInvitedJoinGroupRequestEvent(RequestEvent, BotEvent):
    """Bot 账号接受到来自某个账号的邀请加入某个群组的请求.

    事件拓展支持:
        该事件的处理需要你获取原始事件实例.

        1. 同意请求: `await event.accept()`, 具体查看该方法所附带的说明.
        2. 拒绝请求: `await event.reject()`, 具体查看该方法所附带的说明.
    """

    __event_type__ = "BotInvitedJoinGroupRequestEvent"

    group_name: str = Field(..., alias="groupName")
    """被邀请进入群的群名称"""

    async def accept(self, message: str = "") -> None:
        """接受邀请并加入群组/发起对指定群组的加入申请.

        Args:
            message (str, optional): 附带给对方的消息. 默认为 "".

        Raises:
            LookupError: 尝试上下文外处理事件.
            InvalidSession: 应用实例没准备好!

        Returns:
            None: 没有返回.
        """
        await self._operate(0, message)

    async def reject(self, message: str = "") -> None:
        """拒绝对方加入指定群组的邀请.

        Args:
            message (str, optional): 附带给对方的消息. 默认为 "".

        Raises:
            LookupError: 尝试上下文外处理事件.
            InvalidSession: 应用实例没准备好!

        Returns:
            None: 没有返回.
        """
        await self._operate(1, message)


class ClientKind(int, Enum):
    """详细设备类型。"""

    ANDROID_PAD = 68104
    AOL_CHAOJIHUIYUAN = 73730
    AOL_HUIYUAN = 73474
    AOL_SQQ = 69378
    CAR = 65806
    HRTX_IPHONE = 66566
    HRTX_PC = 66561
    MC_3G = 65795
    MISRO_MSG = 69634
    MOBILE_ANDROID = 65799
    MOBILE_ANDROID_NEW = 72450
    MOBILE_HD = 65805
    MOBILE_HD_NEW = 71426
    MOBILE_IPAD = 68361
    MOBILE_IPAD_NEW = 72194
    MOBILE_IPHONE = 67586
    MOBILE_OTHER = 65794
    MOBILE_PC_QQ = 65793
    MOBILE_PC_TIM = 77313
    MOBILE_WINPHONE_NEW = 72706
    QQ_FORELDER = 70922
    QQ_SERVICE = 71170
    TV_QQ = 69130
    WIN8 = 69899
    WINPHONE = 65804


@register_event_class
class OtherClientOnlineEvent(NoticeEvent):
    """Bot 账号在其他客户端上线."""

    __event_type__ = "OtherClientOnlineEvent"

    client: OtherClient
    """上线的客户端"""

    kind: Optional[ClientKind] = None
    """客户端类型"""


@register_event_class
class OtherClientOfflineEvent(NoticeEvent):
    """Bot 账号在其他客户端下线."""

    __event_type__ = "OtherClientOfflineEvent"

    client: OtherClient
    """下线的客户端"""
