import io
import os
import re
import base64
from enum import Enum
from datetime import datetime
from typing_extensions import override
from collections.abc import Iterable, AsyncGenerator
from typing import IO, TYPE_CHECKING, Any, Union, Optional, cast, overload

from nonebot.message import handle_event
from nonebot.compat import type_validate_python
from nonebot.internal.matcher import current_event

from nonebot.adapters import Bot as BaseBot

from .config import ClientInfo
from .utils import API, log, camel_to_snake
from .message import Image, Video, Voice, Message, MessageSegment
from .model import (
    Group,
    Friend,
    Member,
    Profile,
    FileInfo,
    Stranger,
    MemberInfo,
    GroupConfig,
    OtherClient,
    Announcement,
)
from .event import (
    EVENT_CLASSES,
    Event,
    GroupEvent,
    NudgeEvent,
    FriendEvent,
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


class UploadMethod(str, Enum):
    """用于向 `upload` 系列方法描述上传类型"""

    Friend = "friend"
    """好友"""

    Group = "group"
    """群组"""

    Temp = "temp"
    """临时消息"""

    def __str__(self) -> str:
        return self.value


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
        if isinstance(event, FriendEvent):
            return await self.send_message(event.friend, message, **kwargs)
        if isinstance(event, (GroupEvent, MemberEvent)):
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
    async def get_version(self) -> str:
        """获取 Mirai API HTTP 插件版本.

        Returns:
            str: 版本信息.
        """
        result = await self.adapter.call(self, "about", "get", session=False)
        return result["version"]

    @API
    async def get_bot_list(self) -> list[int]:
        """获取账号列表.

        Returns:
            list[int]: 账号列表.
        """
        result = await self.adapter.call(self, "botList", "get", session=False)
        return result  # type: ignore

    async def get_file_iterator(
        self,
        target: Union[Group, int],
        id: str = "",
        offset: int = 0,
        size: int = 1,
        with_download_info: bool = False,
    ) -> AsyncGenerator[FileInfo, None]:
        """
        以生成器形式列出指定文件夹下的所有文件.

        Args:
            target (Union[Group, int]): 要列出文件的根位置, 为群组或群号 (当前仅支持群组)
            id (str): 文件夹ID, 空串为根目录
            offset (int): 起始分页偏移
            size (int): 单次分页大小
            with_download_info (bool): 是否携带下载信息, 无必要不要携带

        Returns:
            AsyncGenerator[FileInfo, None]: 文件信息生成器.
        """
        target = int(target)
        current_offset = offset
        cache: list[FileInfo] = []
        while True:
            for file_info in cache:
                yield file_info
            cache = await self.get_file_list(
                target=target,
                id=id,
                offset=current_offset,
                size=size,
                with_download_info=with_download_info,
            )
            current_offset += len(cache)
            if not cache:
                return

    @API
    async def get_file_list(
        self,
        *,
        target: Union[Group, int],
        id: str = "",
        offset: Optional[int] = 0,
        size: Optional[int] = 1,
        with_download_info: bool = False,
    ) -> list[FileInfo]:
        """
        列出指定文件夹下的所有文件.

        Args:
            target (Union[Group, int]): 要列出文件的根位置, 为群组或群号 (当前仅支持群组)
            id (str): 文件夹ID, 空串为根目录
            offset (int): 分页偏移
            size (int): 分页大小
            with_download_info (bool): 是否携带下载信息, 无必要不要携带

        Returns:
            List[FileInfo]: 返回的文件信息列表.
        """
        target = int(target)

        result = await self.adapter.call(
            self,
            "file_list",
            "get",
            {
                "id": id,
                "target": target,
                "withDownloadInfo": str(with_download_info),  # yarl don't accept boolean
                "offset": offset,
                "size": size,
            },
        )
        return [type_validate_python(FileInfo, i) for i in result]

    @API
    async def get_file_info(
        self,
        *,
        target: Union[Friend, Group, int],
        id: str = "",
        with_download_info: bool = False,
    ) -> FileInfo:
        """
        获取指定文件的信息.

        Args:
            target (Union[Friend, Group, int]): 要列出文件的根位置, 为群组或好友或QQ号 (当前仅支持群组)
            id (str): 文件ID, 空串为根目录
            with_download_info (bool): 是否携带下载信息, 无必要不要携带

        Returns:
            FileInfo: 返回的文件信息.
        """
        if isinstance(target, Friend):
            raise NotImplementedError("Not implemented for friend")

        target = target.id if isinstance(target, Friend) else target
        target = target.id if isinstance(target, Group) else target

        result = await self.adapter.call(
            self,
            "file_info",
            "get",
            {
                "id": id,
                "target": target,
                "withDownloadInfo": str(with_download_info),  # yarl don't accept boolean
            },
        )

        return type_validate_python(FileInfo, result)

    @API
    async def make_directory(
        self,
        *,
        target: Union[Friend, Group, int],
        name: str,
        id: str = "",
    ) -> FileInfo:
        """
        在指定位置创建新文件夹.

        Args:
            target (Union[Friend, Group, int]): 要列出文件的根位置, 为群组或好友或QQ号 (当前仅支持群组)
            name (str): 要创建的文件夹名称.
            id (str): 上级文件夹ID, 空串为根目录

        Returns:
            FileInfo: 新创建文件夹的信息.
        """
        if isinstance(target, Friend):
            raise NotImplementedError("Not implemented for friend")

        target = target.id if isinstance(target, Friend) else target
        target = target.id if isinstance(target, Group) else target

        result = await self.adapter.call(
            self,
            "file_mkdir",
            "post",
            {
                "id": id,
                "directoryName": name,
                "target": target,
            },
        )

        return type_validate_python(FileInfo, result)

    @API
    async def delete_file(
        self,
        *,
        target: Union[Friend, Group, int],
        id: str = "",
    ) -> None:
        """
        删除指定文件.

        Args:
            target (Union[Friend, Group, int]): 要列出文件的根位置, 为群组或好友或QQ号 (当前仅支持群组)
            id (str): 文件ID

        Returns:
            None: 没有返回.
        """
        if isinstance(target, Friend):
            raise NotImplementedError("Not implemented for friend")

        target = target.id if isinstance(target, Friend) else target
        target = target.id if isinstance(target, Group) else target

        await self.adapter.call(
            self,
            "file_delete",
            "post",
            {
                "id": id,
                "target": target,
            },
        )

    @API
    async def move_file(
        self,
        *,
        target: Union[Friend, Group, int],
        id: str = "",
        dest_id: str = "",
    ) -> None:
        """
        移动指定文件.

        Args:
            target (Union[Friend, Group, int]): 要列出文件的根位置, 为群组或好友或QQ号 (当前仅支持群组)
            id (str): 源文件ID
            dest_id (str): 目标文件夹ID

        Returns:
            None: 没有返回.
        """
        if isinstance(target, Friend):
            raise NotImplementedError("Not implemented for friend")

        target = target.id if isinstance(target, Friend) else target
        target = target.id if isinstance(target, Group) else target

        await self.adapter.call(
            self,
            "file_move",
            "post",
            {
                "id": id,
                "target": target,
                "moveTo": dest_id,
            },
        )

    @API
    async def rename_file(
        self,
        *,
        target: Union[Friend, Group, int],
        id: str = "",
        dest_name: str = "",
    ) -> None:
        """
        重命名指定文件.

        Args:
            target (Union[Friend, Group, int]): 要列出文件的根位置, 为群组或好友或QQ号 (当前仅支持群组)
            id (str): 源文件ID
            dest_name (str): 目标文件新名称.

        Returns:
            None: 没有返回.
        """
        if isinstance(target, Friend):
            raise NotImplementedError("Not implemented for friend")

        target = target.id if isinstance(target, Friend) else target
        target = target.id if isinstance(target, Group) else target

        await self.adapter.call(
            self,
            "file_rename",
            "post",
            {
                "id": id,
                "target": target,
                "renameTo": dest_name,
            },
        )

    @staticmethod
    def _upload_method(method: Union[UploadMethod, Event]):
        if isinstance(method, UploadMethod):
            return str(method).lower()
        if isinstance(method, (FriendMessage, FriendEvent)):
            return "friend"
        if isinstance(method, (GroupMessage, GroupEvent, MemberEvent)):
            return "group"
        if isinstance(method, TempMessage):
            return "temp"
        if isinstance(method, NudgeEvent):
            return method.scene
        raise ValueError(f"Unknown upload method: {method}")

    @API
    async def upload_file(
        self,
        *,
        data: Union[bytes, IO[bytes], os.PathLike],
        method: Union[UploadMethod, Event],
        target: Union[Friend, Group, int] = -1,
        path: str = "",
        name: str = "",
    ) -> "FileInfo":
        """
        上传文件到指定目标, 需要提供: 文件的原始数据(bytes), 文件的上传类型, 上传目标, (可选)上传目录ID.

        Args:
            data (Union[bytes, IO[bytes], os.PathLike]): 文件的原始数据
            method (UploadMethod | Event): 文件的上传类型
            target (Union[Friend, Group, int]): 文件上传目标, 即群组
            path (str): 目标路径, 默认为根路径.
            name (str): 文件名, 可选, 若 path 存在斜杠可从 path 推断.

        Returns:
            FileInfo: 文件信息
        """
        _method = self._upload_method(method)

        if _method != "group":
            raise NotImplementedError(f"Not implemented for {_method}")

        target = target.id if isinstance(target, (Friend, Group)) else target

        if "/" in path and not name:
            path, name = path.rsplit("/", 1)

        if isinstance(data, os.PathLike):
            data = open(data, "rb")

        result = await self.adapter.call(
            self,
            "file_upload",
            "multipart",
            {
                "type": _method,
                "target": str(target),
                "path": path,
                "file": {"value": data, **({"filename": name} if name else {})},
            },
        )

        return type_validate_python(FileInfo, result)

    @API
    async def upload_image(
        self,
        *,
        method: Union[UploadMethod, Event],
        data: Union[bytes, IO[bytes], os.PathLike, None] = None,
        url: Optional[str] = None,
    ) -> Image:
        """上传一张图片到远端服务器, 需要提供: 图片的原始数据(bytes), 图片的上传类型.

        Args:
            method (UploadMethod | Event): 图片的上传类型, 可从上下文推断
            data (Union[bytes, IO[bytes], os.PathLike], optional): 图片的原始数据
            url (str, optional): 图片的 URL
        Returns:
            Image: 生成的图片消息元素
        """
        if not data and not url:
            raise ValueError("Either data or url must be provided")

        _method = self._upload_method(method)

        if isinstance(data, os.PathLike):
            data = open(data, "rb")

        result = await self.adapter.call(
            self,
            "uploadImage",
            "multipart",
            {
                "type": _method,
                "img": data,
                "url": url,
            },
        )

        return Image.parse(result)

    @API
    async def upload_voice(
        self,
        *,
        method: Union[UploadMethod, Event],
        data: Union[bytes, IO[bytes], os.PathLike, None] = None,
        url: Optional[str] = None,
    ) -> Voice:
        """上传语音到远端服务器, 需要提供: 语音的原始数据(bytes), 语音的上传类型.

        Args:
            method (UploadMethod | Event): 语音的上传类型, 可从上下文推断
            data (Union[bytes, IO[bytes], os.PathLike], optional): 语音的原始数据
            url (str, optional): 语音的 URL
        Returns:
            Voice: 生成的语音消息元素
        """
        if not data and not url:
            raise ValueError("Either data or url must be provided")

        _method = self._upload_method(method)

        if isinstance(data, os.PathLike):
            data = open(data, "rb")

        result = await self.adapter.call(
            self,
            "uploadVoice",
            "multipart",
            {
                "type": _method,
                "voice": data,
                "url": url,
            },
        )

        return Voice.parse(result)

    @API
    async def upload_video(
        self,
        *,
        method: Union[UploadMethod, Event],
        data: Union[bytes, IO[bytes], os.PathLike],
        thumbnail: Union[bytes, IO[bytes], os.PathLike],
    ) -> Video:
        """上传一段视频到远端服务器, 需要提供: 视频的原始数据(bytes), 视频的上传类型，视频的封面.

        Args:
            method (UploadMethod | Event): 图片的上传类型, 可从上下文推断
            data (Union[bytes, IO[bytes], os.PathLike]): 视频的原始数据
            thumbnail (Union[bytes, IO[bytes], os.PathLike]): 视频的封面
        Returns:
            Image: 生成的图片消息元素
        """
        _method = self._upload_method(method)

        if isinstance(data, os.PathLike):
            data = open(data, "rb")
        if isinstance(thumbnail, os.PathLike):
            thumbnail = open(thumbnail, "rb")

        result = await self.adapter.call(
            self,
            "uploadShortVideo",
            "multipart",
            {
                "type": _method,
                "video": data,
                "thumbnail": thumbnail,
            },
        )

        return Video.parse(result)

    @API
    async def get_announcement_list(
        self,
        *,
        target: Union[Group, int],
        offset: Optional[int] = 0,
        size: Optional[int] = 10,
    ) -> list[Announcement]:
        """
        列出群组下所有的公告.

        Args:
            target (Union[Group, int]): 指定的群组.
            offset (Optional[int], optional): 起始偏移量. 默认为 0.
            size (Optional[int], optional): 列表大小. 默认为 10.

        Returns:
            List[Announcement]: 列出群组下所有的公告.
        """
        result = await self.adapter.call(
            self,
            "anno_list",
            "get",
            {
                "target": int(target),
                "offset": offset,
                "size": size,
            },
        )

        return [type_validate_python(Announcement, announcement) for announcement in result]

    @API
    async def publish_announcement(
        self,
        *,
        target: Union[Group, int],
        content: str,
        send_to_new_member: bool = False,
        pinned: bool = False,
        show_edit_card: bool = False,
        show_popup: bool = False,
        require_confirmation: bool = False,
        image: Optional[Union[str, bytes, os.PathLike, io.IOBase]] = None,
    ) -> Announcement:
        """
        发布一个公告.

        Args:
            target (Union[Group, int]): 指定的群组.
            content (str): 公告内容.
            send_to_new_member (bool, optional): 是否公开. 默认为 False.
            pinned (bool, optional): 是否置顶. 默认为 False.
            show_edit_card (bool, optional): 是否自动删除. 默认为 False.
            show_popup (bool, optional): 是否在阅读后自动删除. 默认为 False.
            require_confirmation (bool, optional): 是否需要确认. 默认为 False.
            image (Union[str, bytes, os.PathLike, io.IOBase, Image], optional): 图片. 默认为 None. \
            为 str 时代表 url, 为 bytes / os.PathLike / io.IOBase 代表原始数据

        Raises:
            TypeError: 提供了错误的参数, 阅读有关文档得到问题原因

        Returns:
            None: 没有返回.
        """
        data: dict[str, Any] = {
            "target": int(target),
            "content": content,
            "sendToNewMember": send_to_new_member,
            "pinned": pinned,
            "showEditCard": show_edit_card,
            "showPopup": show_popup,
            "requireConfirmation": require_confirmation,
        }

        if image:
            if isinstance(image, bytes):
                data["imageBase64"] = base64.b64encode(image).decode("ascii")
            elif isinstance(image, os.PathLike):
                data["imageBase64"] = base64.b64encode(open(image, "rb").read()).decode("ascii")
            elif isinstance(image, io.IOBase):
                data["imageBase64"] = base64.b64encode(image.read()).decode("ascii")
            elif isinstance(image, str):
                data["imageUrl"] = image

        result = await self.adapter.call(
            self,
            "anno_publish",
            "post",
            data,
        )
        return type_validate_python(Announcement, result)

    @API
    async def delete_announcement(self, *, target: Union[Group, int], anno: Union[Announcement, int]) -> None:
        """
        删除一条公告.

        Args:
            target (Union[Group, int]): 指定的群组.
            anno (Union[Announcement, int]): 指定的公告.

        Raises:
            TypeError: 提供了错误的参数, 阅读有关文档得到问题原因
        """
        await self.adapter.call(
            self,
            "anno_delete",
            "post",
            {
                "target": int(target),
                "anno": anno.fid if isinstance(anno, Announcement) else anno,
            },
        )

    @API
    async def delete_friend(self, *, target: Union[Friend, int]) -> None:
        """
        删除指定好友.

        Args:
            target (Union[Friend, int]): 好友对象或QQ号.

        Returns:
            None: 没有返回.
        """
        friend_id = target.id if isinstance(target, Friend) else target

        await self.adapter.call(
            self,
            "deleteFriend",
            "post",
            {
                "target": friend_id,
            },
        )

    @API
    async def mute_member(self, *, group: Union[Group, int], member: Union[Member, int], time: int) -> None:
        """
        在指定群组禁言指定群成员; 需要具有相应权限(管理员/群主);
        `time` 不得大于 `30*24*60*60=2592000` 或小于 `0`, 否则会自动修正;
        当 `time` 小于等于 `0` 时, 不会触发禁言操作;
        禁言对象极有可能触发 `PermissionError`, 在这之前请对其进行判断!

        Args:
            group (Union[Group, int]): 指定的群组
            member (Union[Member, int]): 指定的群成员(只能是普通群员或者是管理员, 后者则要求群主权限)
            time (int): 禁言事件, 单位秒, 修正规则: `0 < time <= 2592000`

        Raises:
            PermissionError: 没有相应操作权限.

        Returns:
            None: 没有返回.
        """
        time = max(0, min(time, 2592000))  # Fix time parameter
        if not time:
            return
        await self.adapter.call(
            self,
            "mute",
            "post",
            {
                "target": group.id if isinstance(group, Group) else group,
                "memberId": member.id if isinstance(member, Member) else member,
                "time": time,
            },
        )

    @API
    async def unmute_member(self, *, group: Union[Group, int], member: Union[Member, int]) -> None:
        """
        在指定群组解除对指定群成员的禁言;
        需要具有相应权限(管理员/群主);
        对象极有可能触发 `PermissionError`, 在这之前请对其进行判断!

        Args:
            group (Union[Group, int]): 指定的群组
            member (Union[Member, int]): 指定的群成员(只能是普通群员或者是管理员, 后者则要求群主权限)

        Raises:
            PermissionError: 没有相应操作权限.

        Returns:
            None: 没有返回.
        """
        await self.adapter.call(
            self,
            "unmute",
            "post",
            {
                "target": group.id if isinstance(group, Group) else group,
                "memberId": member.id if isinstance(member, Member) else member,
            },
        )

    @API
    async def mute_all(self, *, group: Union[Group, int]) -> None:
        """在指定群组开启全体禁言, 需要当前会话账号在指定群主有相应权限(管理员或者群主权限)

        Args:
            group (Union[Group, int]): 指定的群组.

        Returns:
            None: 没有返回.
        """
        await self.adapter.call(
            self,
            "muteAll",
            "post",
            {
                "target": group.id if isinstance(group, Group) else group,
            },
        )

    @API
    async def unmute_all(self, *, group: Union[Group, int]) -> None:
        """在指定群组关闭全体禁言, 需要当前会话账号在指定群主有相应权限(管理员或者群主权限)

        Args:
            group (Union[Group, int]): 指定的群组.

        Returns:
            None: 没有返回.
        """
        await self.adapter.call(
            self,
            "unmuteAll",
            "post",
            {
                "target": group.id if isinstance(group, Group) else group,
            },
        )

    @API
    async def kick_member(
        self, *, group: Union[Group, int], member: Union[Member, int], message: str = "", block: bool = False
    ) -> None:
        """
        将目标群组成员从指定群组踢出; 需要具有相应权限(管理员/群主)

        Args:
            group (Union[Group, int]): 指定的群组
            member (Union[Member, int]): 指定的群成员(只能是普通群员或者是管理员, 后者则要求群主权限)
            message (str, optional): 对踢出对象要展示的消息
            block (bool, optional): 是否不再接受该成员加群申请

        Returns:
            None: 没有返回.
        """
        await self.adapter.call(
            self,
            "kick",
            "post",
            {
                "target": group.id if isinstance(group, Group) else group,
                "memberId": member.id if isinstance(member, Member) else member,
                "msg": message,
                "block": block,
            },
        )

    @API
    async def quit_group(self, *, group: Union[Group, int]) -> None:
        """
        主动从指定群组退出

        Args:
            group (Union[Group, int]): 需要退出的指定群组

        Returns:
            None: 没有返回.
        """
        await self.adapter.call(
            self,
            "quit",
            "post",
            {
                "target": group.id if isinstance(group, Group) else group,
            },
        )

    @API
    async def set_essence(
        self,
        *,
        message: Union[GroupMessage, ActiveGroupMessage, int],
        target: Union[Group, int, None] = None,
    ) -> None:
        """
        添加指定消息为群精华消息; 需要具有相应权限(管理员/群主).

        请自行判断消息来源是否为群组.

        Args:
            message (Union[GroupMessage, ActiveGroupMessage, Source, int]): 指定的消息.
            target (Union[Group, int]): 指定的群组. message 类型为 int 时必需.

        Returns:
            None: 没有返回.
        """
        if isinstance(message, GroupMessage):
            target = message.sender.group
        elif isinstance(message, ActiveGroupMessage):
            target = message.subject

        if tuple(map(int, (await self.get_version()).split("."))) >= (2, 6, 0):
            if not target:
                event = current_event.get()
                if isinstance(event, GroupMessage):
                    target = event.sender.group
                elif isinstance(event, ActiveGroupMessage):
                    target = event.subject
            if not target:
                raise ValueError("target is required in version 2.6.0+")
            params = {
                "messageId": int(message),
                "target": int(target),
            }
        else:
            params = {
                "target": int(message),
            }

        await self.adapter.call(self, "setEssence", "post", params)

    @API
    async def get_group_config(self, *, group: Union[Group, int]) -> GroupConfig:
        """
        获取指定群组的群设置

        Args:
            group (Union[Group, int]): 需要获取群设置的指定群组

        Returns:
            GroupConfig: 指定群组的群设置
        """
        result = await self.adapter.call(
            self,
            "groupConfig",
            "get",
            {
                "target": group.id if isinstance(group, Group) else group,
            },
        )

        return type_validate_python(GroupConfig, {camel_to_snake(k): v for k, v in result.items()})

    @API
    async def modify_group_config(self, *, group: Union[Group, int], config: GroupConfig) -> None:
        """修改指定群组的群设置; 需要具有相应权限(管理员/群主).

        Args:
            group (Union[Group, int]): 需要修改群设置的指定群组
            config (GroupConfig): 经过修改后的群设置

        Returns:
            None: 没有返回.
        """
        await self.adapter.call(
            self,
            "groupConfig",
            "post",
            {
                "target": group.id if isinstance(group, Group) else group,
                "config": config.dict_(exclude_unset=True, exclude_none=True, to_camel=True),
            },
        )

    @API
    async def modify_member_info(
        self,
        *,
        member: Union[Member, int],
        info: MemberInfo,
        group: Optional[Union[Group, int]] = None,
    ) -> None:
        """
        修改指定群组成员的可修改状态; 需要具有相应权限(管理员/群主).

        Args:
            member (Union[Member, int]): \
                指定的群组成员, 可为 Member 实例, 若前设成立, 则不需要提供 group.
            info (MemberInfo): 已修改的指定群组成员的可修改状态
            group (Optional[Union[Group, int]], optional): \
                如果 member 为 Member 实例, 则不需要提供本项, 否则需要. 默认为 None.

        Raises:
            TypeError: 提供了错误的参数, 阅读有关文档得到问题原因

        Returns:
            None: 没有返回.
        """
        if group is None:
            if isinstance(member, Member):
                group = member.group
            else:
                raise TypeError(
                    "you should give a Member instance if you cannot give a Group instance to me."
                )
        await self.adapter.call(
            self,
            "memberInfo",
            "post",
            {
                "target": group.id if isinstance(group, Group) else group,
                "memberId": member.id if isinstance(member, Member) else member,
                "info": info.dict_(exclude_none=True, exclude_unset=True),
            },
        )

    @API
    async def modify_member_admin(
        self,
        *,
        assign: bool,
        member: Union[Member, int],
        group: Optional[Union[Group, int]] = None,
    ) -> None:
        """
        修改一位群组成员管理员权限; 需要有相应权限(群主)

        Args:
            member (Union[Member, int]): 指定群成员, 可为 Member 实例, 若前设成立, 则不需要提供 group.
            assign (bool): 是否设置群成员为管理员.
            group (Optional[Union[Group, int]], optional): \
                如果 member 为 Member 实例, 则不需要提供本项, 否则需要. 默认为 None.

        Raises:
            TypeError: 提供了错误的参数, 阅读有关文档得到问题原因
            PermissionError: 没有相应操作权限.

        Returns:
            None: 没有返回.
        """
        if group is None:
            if isinstance(member, Member):
                group = member.group
            else:
                raise TypeError(
                    "you should give a Member instance if you cannot give a Group instance to me."
                )
        await self.adapter.call(
            self,
            "memberAdmin",
            "post",
            {
                "target": group.id if isinstance(group, Group) else group,
                "memberId": member.id if isinstance(member, Member) else member,
                "assign": assign,
            },
        )

    @API
    async def register_command(
        self, *, name: str, alias: Iterable[str] = (), usage: str = "", description: str = ""
    ) -> None:
        """注册一个 mirai-console 指令

        Args:
            name (str): 指令名
            alias (Iterable[str], optional): 指令别名. Defaults to ().
            usage (str, optional): 使用方法字符串. Defaults to "".
            description (str, optional): 描述字符串. Defaults to "".

        """
        await self.adapter.call(
            self,
            "cmd_register",
            "post",
            {
                "name": name,
                "alias": alias,
                "usage": usage,
                "description": description,
            },
        )

    @API
    async def execute_command(self, *, command: Union[str, Iterable[str]]) -> None:
        """执行一条 mirai-console 指令

        Args:
            command (Union[str, Iterable[str]]): 指令字符串.

        """
        if isinstance(command, str):
            command = command.split(" ")
        await self.adapter.call(
            self,
            "cmd_execute",
            "post",
            {
                "command": command,
            },
        )

    @API
    async def get_friend_list(self) -> list[Friend]:
        """获取本实例账号添加的好友列表.

        Returns:
            List[Friend]: 添加的好友.
        """
        return [
            type_validate_python(Friend, i)
            for i in await self.adapter.call(
                self,
                "friendList",
                "get",
                {},
            )
        ]

    @API
    async def get_friend(self, *, target: int) -> Friend:
        """获取指定好友.

        Args:
            target (int): 好友的 QQ 号.

        Returns:
            Friend: 指定的好友.
        """
        return next(i for i in await self.get_friend_list() if i.id == target)

    @API
    async def get_group_list(self) -> list[Group]:
        """获取本实例账号加入的群组列表.

        Returns:
            List[Group]: 加入的群组.
        """
        return [
            type_validate_python(Group, i)
            for i in await self.adapter.call(
                self,
                "groupList",
                "get",
                {},
            )
        ]

    @API
    async def get_group(self, *, target: int) -> Group:
        """获取指定群组.

        Args:
            target (int): 群组的群号.

        Returns:
            Group: 指定的群组.
        """
        return next(i for i in await self.get_group_list() if i.id == target)

    @API
    async def get_member_list(self, *, group: Union[Group, int], cache: bool = True) -> list[Member]:
        """尝试从已知的群组获取对应成员的列表.

        Args:
            group (Union[Group, int]): 已知的群组
            cache (bool, optional): 是否使用缓存. Defaults to True.

        Returns:
            List[Member]: 群内成员的 Member 对象.
        """
        group_id = int(group)

        return [
            type_validate_python(Member, i)
            for i in await (
                self.adapter.call(
                    self,
                    "memberList",
                    "get",
                    {
                        "target": group_id,
                    },
                )
                if cache
                else self.adapter.call(
                    self,
                    "latestMemberList",
                    "get",
                    {
                        "target": group_id,
                        "memberIds": [],
                    },
                )
            )
        ]

    @API
    async def get_member(self, *, group: Union[Group, int], target: int) -> Member:
        """尝试从已知的群组唯一 ID 和已知的群组成员的 ID, 获取对应成员的信息.

        Args:
            group (Union[Group, int]): 已知的群组唯一 ID
            target (int): 已知的群组成员的 ID

        Returns:
            Member: 对应群成员对象
        """

        return type_validate_python(
            Member,
            await self.adapter.call(
                self,
                "memberInfo",
                "get",
                {
                    "target": int(group),
                    "memberId": target,
                },
            ),
        )

    @API
    async def get_bot_profile(self) -> Profile:
        """获取本实例绑定账号的 Profile.

        Returns:
            Profile: 找到的 Profile.
        """
        result = await self.adapter.call(
            self,
            "botProfile",
            "get",
            {},
        )
        return type_validate_python(Profile, result)

    @API
    async def get_user_profile(self, *, target: Union[int, Friend, Member, Stranger]) -> Profile:
        """获取任意 QQ 用户的 Profile. 需要 mirai-api-http 2.5.0+.

        Args:
            target (Union[int, Friend, Member, Stranger]): 任意 QQ 用户.

        Returns:
            Profile: 找到的 Profile.
        """
        result = await self.adapter.call(
            self,
            "userProfile",
            "get",
            {
                "target": int(target),
            },
        )
        return type_validate_python(Profile, result)

    @API
    async def get_friend_profile(self, *, friend: Union[Friend, int]) -> Profile:
        """获取好友的 Profile.

        Args:
            friend (Union[Friend, int]): 查找的好友.

        Returns:
            Profile: 找到的 Profile.
        """
        result = await self.adapter.call(
            self,
            "friendProfile",
            "get",
            {
                "target": int(friend),
            },
        )
        return type_validate_python(Profile, result)

    @API
    async def get_member_profile(
        self, *, member: Union[Member, int], group: Optional[Union[Group, int]] = None
    ) -> Profile:
        """获取群员的 Profile.

        Args:
            member (Union[Member, int]): 群员对象.
            group (Optional[Union[Group, int]], optional): 检索的群. \
                提供 Member 形式的 member 参数后可以不提供.

        Raises:
            ValueError: 没有提供可检索的群 ID.

        Returns:
            Profile: 找到的 Profile 对象.
        """
        member_id = member.id if isinstance(member, Member) else member
        group = group or (member.group if isinstance(member, Member) else None)
        group_id = group.id if isinstance(group, Group) else group
        if not group_id:
            raise ValueError("Missing necessary argument: group")
        result = await self.adapter.call(
            self,
            "memberProfile",
            "get",
            {
                "target": group_id,
                "memberId": member_id,
            },
        )
        return type_validate_python(Profile, result)

    @API
    async def get_message_from_id(
        self,
        *,
        message: int,
        target: Union[Friend, Group, Member, Stranger, OtherClient, int],
    ) -> Union[MessageEvent, ActiveMessage]:
        """从 消息 ID 提取 消息事件.

        Note:
            后端 Mirai HTTP API 版本 >= 2.6.0, 仅指定 message 时,
            将尝试以当前事件来源作为 target.

        Args:
            message (Union[Source, int]): 指定的消息.
            target (Union[Friend, Group, Member, Stranger, Client, int], optional): \
                指定的好友或群组. 非响应器上下文时必需.

        Returns:
            MessageEvent: 提取的事件.
        """

        if tuple(map(int, (await self.get_version()).split("."))) >= (2, 6, 0):
            event = current_event.get()
            if isinstance(event, GroupMessage):
                target = event.sender.group
            elif isinstance(event, MessageEvent):
                target = event.sender
            elif isinstance(message, ActiveMessage):
                target = message.subject
            if not target:
                raise ValueError("target is required in version 2.6.0+")

            params = {
                "messageId": int(message),
                "target": self.info.account if isinstance(target, OtherClient) else int(target),
            }
        else:
            params = {
                "id": int(message),
            }

        result = await self.adapter.call(
            self,
            "messageFromId",
            "get",
            params,
        )
        if "type" not in result:
            raise ValueError(f"Invalid result: {result}")

        event_type = result.pop("type")
        if event_type not in EVENT_CLASSES:
            log(
                "WARNING",
                f"received unsupported event <r><bg #f8bbd0>{event_type}</bg #f8bbd0></r>: {result}",
            )
            event = type_validate_python(Event, result)
            event.__event_type__ = event_type  # type: ignore
        else:
            event = type_validate_python(EVENT_CLASSES[event_type], result)
        return cast(Union[MessageEvent, ActiveMessage], event)

    @API
    async def recall_message(
        self,
        *,
        message: Union[MessageEvent, ActiveMessage, int],
        target: Optional[Union[Friend, Group, Member, Stranger, OtherClient, int]] = None,
    ) -> None:
        """撤回指定的消息;
        撤回自己的消息需要在发出后 2 分钟内才能成功撤回;
        如果在群组内, 需要撤回他人的消息则需要管理员/群主权限.

        Note:
            后端 Mirai HTTP API 版本 >= 2.6.0, 仅指定 message 且类型为 int 时, \
                将尝试以当前事件来源作为 target.

        Args:
            message (Union[MessageEvent, ActiveMessage, Source, int]): 指定的消息.
            target (Union[Friend, Group, Member, Stranger, Client, int], optional): \
                指定的好友或群组. message 类型为 int 时必需.

        Returns:
            None: 没有返回
        """
        if target is not None:
            pass
        elif isinstance(message, GroupMessage):
            target = message.sender.group
        elif isinstance(message, MessageEvent):
            target = message.sender
        elif isinstance(message, ActiveMessage):
            target = message.subject

        if tuple(map(int, (await self.get_version()).split("."))) >= (2, 6, 0):
            if not target:
                event = current_event.get()
                if isinstance(event, GroupMessage):
                    target = event.sender.group
                elif isinstance(event, MessageEvent):
                    target = event.sender
                elif isinstance(message, ActiveMessage):
                    target = message.subject
            if not target:
                raise ValueError("target is required in version 2.6.0+")

            params = {
                "messageId": int(message),
                "target": self.account if isinstance(target, OtherClient) else int(target),
            }
        else:
            params = {
                "target": int(message),
            }

        await self.adapter.call(self, "recall", "post", params)

    @API
    async def send_nudge(
        self, *, target: Union[Friend, Member, int], group: Optional[Union[Group, int]] = None
    ) -> None:
        """
        向指定的群组成员或好友发送戳一戳消息.

        Args:
            target (Union[Friend, Member]): 发送戳一戳的目标.
            group (Union[Group, int], optional): 发送的群组.

        Returns:
            None: 没有返回.
        """
        target_id = target if isinstance(target, int) else target.id

        subject_id = (group.id if isinstance(group, Group) else group) or (
            target.group.id if isinstance(target, Member) else target_id
        )
        kind = "Group" if group or isinstance(target, Member) else "Friend"
        await self.adapter.call(
            self,
            "sendNudge",
            "post",
            {
                "target": target_id,
                "subject": subject_id,
                "kind": kind,
            },
        )

    @API
    async def get_roaming_message(
        self, *, start: datetime, end: datetime, target: Union[Friend, int]
    ) -> list[FriendMessage]:
        """获取漫游消息. 需要 Mirai API HTTP 2.6.0+.

        Args:
            start (datetime): 起始时间.
            end (datetime): 结束时间.
            target (Union[Friend, int]): 漫游消息对象.

        Returns:
            List[FriendMessage]: 漫游消息列表.
        """
        target = target if isinstance(target, int) else target.id
        result = await self.adapter.call(
            self,
            "roamingMessages",
            "post",
            {
                "target": target,
                "start": start.timestamp(),
                "end": end.timestamp(),
            },
        )

        return [type_validate_python(FriendMessage, i) for i in result]
