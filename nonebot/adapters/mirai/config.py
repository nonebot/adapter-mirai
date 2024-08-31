from yarl import URL
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
    only_ws: bool = False
    """是否只使用 WebSocket 进行通信

    为 False 则会使用 WebSocket 接收事件，使用 HTTP 调用 API
    """

    def get_url(self, route: str) -> str:
        return str(URL(f"http://{self.host}:{self.port}") / route)

    def ws_url(self):
        return str(
            (URL(f"ws://{self.host}:{self.port}") / "all").with_query(
                {"qq": self.account, "verifyKey": self.verify_key}
            )
        )


class Config(BaseModel):
    mirai_clients: list[ClientInfo] = Field(default_factory=list)
    """Mirai 客户端配置"""
