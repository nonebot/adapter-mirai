<p align="center">
  <a href="https://nonebot.dev/"><img src="https://camo.githubusercontent.com/32db41bc55fa37e0d0085e4fd70e4e74fd34307f6bb4ebdad235bd1b0c8f4126/68747470733a2f2f6e6f6e65626f742e6465762f6c6f676f2e706e67" width="200" height="200" alt="nonebot"></a>
</p>

<div align="center">

# NoneBot-Adapter-Mirai

_✨ mirai-api-http v2 协议适配 ✨_

</div>

> [!NOTE]
> Mirai 及 mirai-api-http 现处于停滞更新状态
> 
> 本项目仅为仍然使用 mirai-api-http 的用户提供支持


## 配置

修改 NoneBot 配置文件 `.env` 或者 `.env.*`。

### Driver

参考 [driver](https://nonebot.dev/docs/appendices/config#driver) 配置项，添加 `HTTPClient` 和 `WebSocketClient` 支持。

如：

```dotenv
DRIVER=~httpx+~websockets
```

或

```dotenv
DRIVER=~aiohttp
```

### MIRAI_CLIENTS

配置连接配置，如：

```dotenv
MIRAI_CLIENTS='
[
  {
    "host": "localhost",
    "port": "8080",
    "account": 1234567890,
    "verify_key": "xxx"
  }
]
'
```

`host` 与 `port` 为 mirai-api-http 服务的监听地址与端口，

`account` 为当前机器人的 QQ 号，

`verify_key` 为 mirai-api-http 的 `verifyKey`。

## 相关项目/鸣谢

- [mirai-api-http](https://github.com/project-mirai/mirai-api-http)
- [Ariadne](https://github.com/GraiaProject/Ariadne)
