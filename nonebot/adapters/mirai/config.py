from typing import Literal

from pydantic import Field, BaseModel



class ClientInfo(BaseModel):
    host: str = "localhost"
    """Mirai API HTTP 服务器地址"""
    port: int = 8080
    """Mirai API HTTP 服务器端口"""
    account: int
    """Mirai 登录账号"""
    verify_key: str
    """Mirai API HTTP 验证密钥"""
    adapter: set[Literal["http", "ws"]] = {"http", "ws"}
    """Mirai API HTTP 适配器类型

    若只填入了 "http"，则只会通过 HTTP 进行通信
    若只填入了 "ws"，则只会使用 WebSocket 进行通信
    若两者都填入，则会使用 WebSocket 接收事件，使用 HTTP 调用 API
    """


class Config(BaseModel):
    mirai_client: list[ClientInfo] = Field(default_factory=list)
    """Mirai 客户端配置"""
