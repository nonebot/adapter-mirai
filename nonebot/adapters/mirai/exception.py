from typing import Any, Union, Optional

from nonebot.exception import AdapterException
from nonebot.exception import ActionFailed as BaseActionFailed
from nonebot.exception import NetworkError as BaseNetworkError
from nonebot.exception import ApiNotAvailable as BaseApiNotAvailable


class MiraiAdapterException(AdapterException):
    def __init__(self):
        super().__init__("mirai")


class ActionFailed(BaseActionFailed, MiraiAdapterException):
    def __init__(self, msg: str, code: int, headers: Any = None, content: Optional[Union[str, bytes]] = None):
        self.status_code: int = code
        self.message: str = msg
        self.headers = headers
        self.content = content
        super().__init__()

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__}({self.status_code}): {self.message}>: "
            f"headers={self.headers}, content={self.content}>"
        )

    def __str__(self):
        return self.__repr__()


class InvalidVerifyKey(ActionFailed):
    """无效的 verifyKey 或其配置."""


class AccountNotFound(ActionFailed):
    """未能使用所配置的账号激活 session key, 请检查配置."""


class InvalidSession(ActionFailed):
    """无效的 sessionKey, 请重新获取."""


class UnVerifiedSession(ActionFailed):
    """尚未验证/绑定的 session."""


class UnknownTarget(ActionFailed):
    """对象位置未知, 不存在或不可及."""


class FileNotFound(ActionFailed):
    """文件不存在."""


class PermissionDenied(ActionFailed):
    """权限不足."""


class AccountMuted(ActionFailed):
    """账号在对象所在聊天区域被封禁."""


class TooLongMessage(ActionFailed):
    """消息过长, 尝试分段发送或报告问题."""


class InvalidOperation(ActionFailed):
    """操作参数不合法, 请报告问题."""


class ApiNotAvailable(BaseApiNotAvailable, MiraiAdapterException):
    def __init__(self, msg: Optional[str] = None):
        super().__init__()
        self.msg: Optional[str] = msg
        """错误原因"""


class RemoteException(BaseNetworkError, MiraiAdapterException):
    """网络异常: 无头客户端处发生错误, 你应该检查其输出的错误日志."""

    def __init__(
        self, msg: str, code: int, headers: Optional[dict] = None, content: Optional[Union[str, bytes]] = None
    ):
        self.status_code: int = code
        self.message: str = msg
        self.headers = headers
        self.content = content
        super().__init__()

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__}({self.status_code}): {self.message}>: "
            f"headers={self.headers}, content={self.content}>"
        )

    def __str__(self):
        return self.__repr__()


code_exceptions_mapping: dict[int, type[ActionFailed]] = {
    1: InvalidVerifyKey,
    2: AccountNotFound,
    3: InvalidSession,
    4: UnVerifiedSession,
    5: UnknownTarget,
    6: FileNotFound,
    10: PermissionDenied,
    20: AccountMuted,
    30: TooLongMessage,
    400: InvalidOperation,
    500: RemoteException,  # type: ignore
}
