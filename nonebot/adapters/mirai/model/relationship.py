import functools
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Optional

from pydantic import Field
from nonebot.internal.driver import Request
from nonebot.internal.matcher import current_bot

from .base import ModelBase

if TYPE_CHECKING:
    from .common import Profile

_MEMBER_PERM_LV_MAP: dict[str, int] = {
    "MEMBER": 1,
    "ADMINISTRATOR": 2,
    "OWNER": 3,
}

_MEMBER_PERM_REPR_MAP: dict[str, str] = {
    "MEMBER": "<普通成员>",
    "ADMINISTRATOR": "<管理员>",
    "OWNER": "<群主>",
}


@functools.total_ordering
class MemberPerm(Enum):
    """描述群成员在群组中所具备的权限"""

    Member = "MEMBER"  # 普通成员
    Administrator = "ADMINISTRATOR"  # 管理员
    Owner = "OWNER"  # 群主

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: "MemberPerm"):
        return _MEMBER_PERM_LV_MAP[self.value] < _MEMBER_PERM_LV_MAP[other.value]

    def __repr__(self) -> str:
        return _MEMBER_PERM_REPR_MAP[self.value]


class Group(ModelBase):
    """描述 Tencent QQ 中的群组."""

    id: int
    """群号"""

    name: str
    """群名"""

    account_perm: MemberPerm = Field(..., alias="permission")
    """你在群中的权限"""

    kind: Optional[Literal["Group"]] = Field(None, alias="kind")

    def __int__(self):
        return self.id

    def __str__(self) -> str:
        return f"{self.name}({self.id})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Group) and self.id == other.id

    async def get_config(self) -> "GroupConfig":
        """获取该群组的 Config

        Returns:
            Config: 该群组的设置对象.
        """
        bot = current_bot.get()
        return await bot.get_group_config(target=self)

    async def modify_config(self, config: "GroupConfig") -> None:
        """修改该群组的 Config

        Args:
            config (GroupConfig): 经过修改后的群设置对象.
        """
        bot = current_bot.get()
        return await bot.modify_group_config(target=self, config=config)

    async def get_avatar(self, cover: Optional[int] = None) -> bytes:
        """获取该群组的头像
        Args:
            cover (Optional[int]): 群封面标号 (若为 None 则获取该群头像, 否则获取该群封面)

        Returns:
            bytes: 群头像的二进制内容.
        """
        bot = current_bot.get()
        cover = (cover or 0) + 1
        req = Request("GET", f"http://p.qlogo.cn/gh/{self.id}/{self.id}_{cover}/")
        return (await bot.adapter.request(req)).content  # type: ignore


class ActiveStatus(ModelBase):
    """描述群员的活跃状态"""

    rank: int
    """群活跃等级 1-6"""

    point: int
    """群活跃积分"""

    honors: list[str]
    """群荣誉列表"""

    temperature: int
    """群荣誉等级 LV 1-100"""


class Member(ModelBase):
    """描述用户在群组中所具备的有关状态, 包括所在群组, 群中昵称, 所具备的权限, 唯一ID."""

    id: int
    """QQ 号"""

    name: str = Field(..., alias="memberName")
    """显示名称"""

    permission: MemberPerm
    """群权限"""

    special_title: Optional[str] = Field(None, alias="specialTitle")
    """特殊头衔"""

    join_timestamp: Optional[int] = Field(None, alias="joinTimestamp")
    """加入的时间"""

    last_speak_timestamp: Optional[int] = Field(None, alias="lastSpeakTimestamp")
    """最后发言时间"""

    mute_time: Optional[int] = Field(None, alias="mutetimeRemaining")
    """禁言剩余时间"""

    active_status: Optional[ActiveStatus] = Field(None, alias="active")
    """活跃状态"""

    group: Group
    """所在群组"""

    def __str__(self) -> str:
        return f"{self.name}({self.id} @ {self.group})"

    def __int__(self):
        return self.id

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, (Friend, Member, Stranger)) and self.id == other.id

    async def get_profile(self) -> "Profile":
        """获取该群成员的 Profile

        Returns:
            Profile: 该群成员的 Profile 对象
        """
        bot = current_bot.get()
        return await bot.get_member_profile(target=self)

    @property
    def info(self) -> "MemberInfo":
        """获取该成员的可修改状态

        Returns:
            MemberInfo: 群组成员的可修改状态
        """
        return MemberInfo(name=self.name, specialTitle=self.special_title)

    async def modify_info(self, info: "MemberInfo") -> None:
        """
        修改群组成员的可修改状态; 需要具有相应权限(管理员/群主).

        Args:
            info (MemberInfo): 已修改的指定群组成员的可修改状态

        Returns:
            None: 没有返回.
        """
        bot = current_bot.get()
        return await bot.modify_member_info(target=self, info=info)

    async def modify_admin(self, assign: bool) -> None:
        """
        修改一位群组成员管理员权限; 需要有相应权限(群主)

        Args:
            assign (bool): 是否设置群成员为管理员.

        Returns:
            None: 没有返回.
        """
        bot = current_bot.get()
        return await bot.modify_member_admin(target=self, assign=assign)

    async def get_avatar(self, size: Literal[640, 140] = 640) -> bytes:
        """获取该群成员的头像

        Args:
            size (Literal[640, 140]): 头像尺寸

        Returns:
            bytes: 群成员头像的二进制内容.
        """
        bot = current_bot.get()
        req = Request("GET", f"http://q1.qlogo.cn/g?b=qq&nk={self.id}&s={size}")
        return (await bot.adapter.request(req)).content  # type: ignore


class Friend(ModelBase):
    """描述 Tencent QQ 中的好友."""

    id: int
    """QQ 号"""

    nickname: str
    """昵称"""

    remark: str
    """自行设置的代称"""

    def __int__(self):
        return self.id

    def __str__(self) -> str:
        return f"{self.remark}({self.id})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, (Friend, Member, Stranger)) and self.id == other.id

    async def get_profile(self) -> "Profile":
        """获取该好友的 Profile

        Returns:
            Profile: 该好友的 Profile 对象
        """
        bot = current_bot.get()
        return await bot.get_friend_profile(target=self)

    async def get_avatar(self, size: Literal[640, 140] = 640) -> bytes:
        """获取该好友的头像

        Args:
            size (Literal[640, 140]): 头像尺寸

        Returns:
            bytes: 好友头像的二进制内容.
        """
        bot = current_bot.get()
        req = Request("GET", f"http://q1.qlogo.cn/g?b=qq&nk={self.id}&s={size}")
        return (await bot.adapter.request(req)).content  # type: ignore


class Stranger(ModelBase):
    """描述 Tencent QQ 中的陌生人."""

    id: int
    """QQ 号"""

    nickname: str
    """昵称"""

    remark: str
    """自行设置的代称"""

    def __int__(self):
        return self.id

    def __str__(self) -> str:
        return f"Stranger({self.id}, {self.nickname})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, (Friend, Member, Stranger)) and self.id == other.id

    async def get_avatar(self, size: Literal[640, 140] = 640) -> bytes:
        """获取该陌生人的头像

        Args:
            size (Literal[640, 140]): 头像尺寸

        Returns:
            bytes: 陌生人头像的二进制内容.
        """
        bot = current_bot.get()
        req = Request("GET", f"http://q1.qlogo.cn/g?b=qq&nk={self.id}&s={size}")
        return (await bot.adapter.request(req)).content  # type: ignore


class GroupConfig(ModelBase):
    """描述群组各项功能的设置."""

    name: str = ""
    """群名"""

    announcement: str = ""
    """群公告"""

    confess_talk: bool = False
    """开启坦白说"""

    allow_member_invite: bool = False
    """允许群成员直接邀请入群"""

    auto_approve: bool = False
    """自动通过加群申请"""

    anonymous_chat: bool = False
    """允许匿名聊天"""

    mute_all: bool = Field(False, exclude=True)
    """是否在全员禁言"""


class MemberInfo(ModelBase):
    """描述群组成员的可修改状态, 修改需要管理员/群主权限."""

    name: str = ""
    """昵称, 与 nickname不同"""

    special_title: Optional[str] = Field(default="", alias="specialTitle")
    """特殊头衔"""


class OtherClient(ModelBase):
    """
    指示其他客户端
    """

    id: int
    """客户端 ID"""

    platform: str
    """平台字符串表示"""

    kind: Optional[Literal["OtherClient"]] = Field(None, alias="kind")
