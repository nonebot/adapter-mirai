from enum import Enum
from io import BytesIO
from pathlib import Path
from base64 import b64encode
from datetime import datetime
from collections.abc import Iterable
from typing_extensions import override
from dataclasses import field, dataclass
from typing import Union, Literal, ClassVar, Optional, TypedDict, cast, overload

from nonebot.adapters import Message as BaseMessage
from nonebot.adapters import MessageSegment as BaseMessageSegment

from .model import Member


class MessageSegment(BaseMessageSegment["Message"]):
    __element_type__: ClassVar[tuple[str, str]]
    __mapping__: ClassVar[dict[str, str]] = {}
    __rmapping__: ClassVar[dict[str, str]] = {}

    def __init_subclass__(cls, **kwargs):
        if "element_type" in kwargs:
            cls.__element_type__ = kwargs["element_type"]
        if cls.__mapping__:
            cls.__rmapping__ = {v: k for k, v in cls.__mapping__.items()}

    @classmethod
    @override
    def get_message_class(cls) -> type["Message"]:
        # 返回适配器的 Message 类型本身
        return Message

    @classmethod
    def parse(cls, raw: dict):
        return cls(
            cls.__element_type__[1],
            {cls.__rmapping__.get(k, k): v for k, v in raw.items() if k != "type"},
        )

    def dump(self) -> dict:
        return {
            "type": self.__element_type__[0],
            **{self.__mapping__.get(k, k): v for k, v in self.data.items()},
        }

    @override
    def __str__(self) -> str:
        shown_data = {k: v for k, v in self.data.items() if not k.startswith("_")}
        # 返回该消息段的纯文本表现形式，通常在日志中展示
        return self.data["text"] if self.is_text() else f"[{self.type}: {shown_data}]"

    @override
    def is_text(self) -> bool:
        # 判断该消息段是否为纯文本
        return self.type == "text"

    @staticmethod
    def text(content: str) -> "Text":
        """纯文本消息段"""
        return Text("text", {"text": content})

    @staticmethod
    @overload
    def at(target: Literal["all", 0, "0"]) -> "AtAll": ...

    @staticmethod
    @overload
    def at(target: Union[int, str, Member], display: Optional[str] = None) -> "At": ...

    @staticmethod
    def at(target: Union[int, str, Member], display: Optional[str] = None):
        """At 消息段"""
        if target in ("all", "0", 0):
            return AtAll("at_all", {})
        return At("at", {"target": int(target), "display": display})

    @staticmethod
    def at_all():
        """At 全体成员消息段"""
        return AtAll("at_all", {})

    @staticmethod
    def face(face_id: int, name: Optional[str] = None, superface: Optional[bool] = None) -> "Face":
        """表情消息段"""
        return Face("face", {"id": face_id, "name": name, "superface": superface})

    @staticmethod
    def market_face(face_id: int, name: Optional[str] = None) -> "MarketFace":
        """商城表情消息段"""
        return MarketFace("market_face", {"id": face_id, "name": name})

    @staticmethod
    def json(content: str) -> "Json":
        """JSON 消息段"""
        return Json("json", {"json": content})

    @staticmethod
    def xml(content: str) -> "Xml":
        """XML 消息段"""
        return Xml("xml", {"xml": content})

    @staticmethod
    def app(content: str) -> "App":
        """APP 消息段"""
        return App("app", {"content": content})

    @staticmethod
    def poke(name: Union[str, "PokeMethods"]) -> "Poke":
        """戳一戳(窗口摇动) 消息段

        请与 '双击头像' 区分，后者是单独的行为，而非消息元素。
        """
        return Poke("poke", {"name": PokeMethods(name)})

    @staticmethod
    def dice(value: int) -> "Dice":
        """随机骰子消息段"""
        return Dice("dice", {"value": value})

    @staticmethod
    def music(
        kind: Union[str, "MusicShareKind"],
        title: Optional[str] = None,
        summary: Optional[str] = None,
        jump_url: Optional[str] = None,
        picture_url: Optional[str] = None,
        music_url: Optional[str] = None,
        brief: Optional[str] = None,
    ) -> "Music":
        """音乐分享消息段"""
        return Music(
            "music",
            {
                "kind": MusicShareKind(kind),
                "title": title,
                "summary": summary,
                "jump_url": jump_url,
                "picture_url": picture_url,
                "music_url": music_url,
                "brief": brief,
            },
        )

    @staticmethod
    def custom_node(uid: int, time: datetime, name: str, message: "Message") -> "CustomNode":
        """合并转发消息段中的自定义节点"""
        return CustomNode(uid, int(time.timestamp()), name, message)

    @staticmethod
    def id_node(id: int) -> "IdNode":
        """合并转发消息段中的当前对话上下文消息引用节点"""
        return IdNode(id)

    @staticmethod
    def ref_node(id: int, target: Optional[int] = None) -> "RefNode":
        """合并转发消息段中的其他对话上下文消息引用节点"""
        return RefNode({"id": id, "target": target})

    @staticmethod
    def forward(
        nodes: list[Union["CustomNode", "IdNode", "RefNode"]],
        display_strategy: Optional["DisplayStrategy"] = None,
    ) -> "Forward":
        """合并转发消息段"""
        return Forward("forward", {"nodes": nodes, "display_strategy": display_strategy})

    @staticmethod
    def image(
        id: Optional[str] = None,
        url: Optional[str] = None,
        *,
        path: Optional[Union[Path, str]] = None,
        base64: Optional[str] = None,
        raw: Union[None, bytes, BytesIO] = None,
    ) -> "Image":
        """图片消息段"""
        if sum([bool(url), bool(path), bool(base64), bool(raw)]) > 1:
            raise ValueError("Too many binary initializers!")
        if path:
            _path = Path(path)
            if not _path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            _base64 = b64encode(_path.read_bytes()).decode()
        elif base64:
            _base64 = base64
        elif raw:
            if isinstance(raw, BytesIO):
                _base64 = b64encode(raw.read()).decode()
            else:
                _base64 = b64encode(raw).decode()
        else:
            _base64 = None
        return Image("image", {"id": id, "url": url, "base64": _base64})

    @staticmethod
    def flash_image(
        id: Optional[str] = None,
        url: Optional[str] = None,
        *,
        path: Optional[Union[Path, str]] = None,
        base64: Optional[str] = None,
        raw: Union[None, bytes, BytesIO] = None,
    ) -> "FlashImage":
        """闪照消息段"""
        if sum([bool(url), bool(path), bool(base64), bool(raw)]) > 1:
            raise ValueError("Too many binary initializers!")
        if path:
            _path = Path(path)
            if not _path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            _base64 = b64encode(_path.read_bytes()).decode()
        elif base64:
            _base64 = base64
        elif raw:
            if isinstance(raw, BytesIO):
                _base64 = b64encode(raw.read()).decode()
            else:
                _base64 = b64encode(raw).decode()
        else:
            _base64 = None
        return FlashImage("flash_image", {"id": id, "url": url, "base64": _base64})

    @staticmethod
    def voice(
        id: Optional[str] = None,
        url: Optional[str] = None,
        *,
        path: Optional[Union[Path, str]] = None,
        base64: Optional[str] = None,
        raw: Union[None, bytes, BytesIO] = None,
        length: Optional[int] = None,
    ) -> "Voice":
        """语音消息段"""
        if sum([bool(url), bool(path), bool(base64), bool(raw)]) > 1:
            raise ValueError("Too many binary initializers!")
        if path:
            _path = Path(path)
            if not _path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            _base64 = b64encode(_path.read_bytes()).decode()
        elif base64:
            _base64 = base64
        elif raw:
            if isinstance(raw, BytesIO):
                _base64 = b64encode(raw.read()).decode()
            else:
                _base64 = b64encode(raw).decode()
        else:
            _base64 = None
        return Voice("voice", {"id": id, "url": url, "base64": _base64, "length": length})

    @staticmethod
    def video(
        id: str, md5: str, size: int, format: str, name: str, url: str, thumbnail: Optional[str] = None
    ) -> "Video":
        """短视频消息段"""
        return Video(
            "video",
            {
                "id": id,
                "md5": md5,
                "size": size,
                "format": format,
                "name": name,
                "url": url,
                "thumbnail": thumbnail,
            },
        )

    @staticmethod
    def reply(message_id: int) -> "MessageSegment":
        """回复消息段，仅发生可用"""
        return MessageSegment("$mirai:reply", {"id": message_id})


class TextData(TypedDict):
    text: str


@dataclass
class Text(MessageSegment, element_type=("Plain", "text")):
    data: TextData = field(default_factory=dict)  # type: ignore


class AtData(TypedDict):
    target: int
    display: Optional[str]


@dataclass
class At(MessageSegment, element_type=("At", "at")):
    data: AtData = field(default_factory=dict)  # type: ignore

    @override
    def __str__(self):
        return f"@{self.data.get('display', self.data['target'])}"


@dataclass
class AtAll(MessageSegment, element_type=("AtAll", "at_all")):
    data: dict = field(default_factory=dict)

    @override
    def __str__(self):
        return "@全体成员"


class FaceData(TypedDict):
    id: int
    name: Optional[str]
    superface: Optional[bool]


@dataclass
class Face(MessageSegment, element_type=("Face", "face")):
    data: FaceData = field(default_factory=dict)  # type: ignore

    __mapping__ = {
        "id": "faceId",
        "superface": "superFace",
    }

    @override
    def __str__(self):
        return f"[表情:{self.data['id']}]"


class MarketFaceData(TypedDict):
    id: int
    name: Optional[str]


@dataclass
class MarketFace(MessageSegment, element_type=("MarketFace", "market_face")):
    data: MarketFaceData = field(default_factory=dict)  # type: ignore

    @override
    def __str__(self):
        return f"[商城表情:{self.data['id']}]"


class JsonData(TypedDict):
    json: str


@dataclass
class Json(MessageSegment, element_type=("Json", "json")):
    data: JsonData = field(default_factory=dict)  # type: ignore

    @override
    def __str__(self):
        return "[JSON消息]"


class XmlData(TypedDict):
    xml: str


@dataclass
class Xml(MessageSegment, element_type=("Xml", "xml")):
    data: XmlData = field(default_factory=dict)  # type: ignore

    @override
    def __str__(self):
        return "[XML消息]"


class AppData(TypedDict):
    content: str


@dataclass
class App(MessageSegment, element_type=("App", "app")):
    data: AppData = field(default_factory=dict)  # type: ignore

    @override
    def __str__(self):
        return "[APP消息]"


class PokeMethods(str, Enum):
    """戳一戳(窗口摇动)的可用方法"""

    ChuoYiChuo = "ChuoYiChuo"
    """戳一戳"""

    BiXin = "BiXin"
    """比心"""

    DianZan = "DianZan"
    """点赞"""

    XinSui = "XinSui"
    """心碎"""

    LiuLiuLiu = "LiuLiuLiu"
    """666"""

    FangDaZhao = "FangDaZhao"
    """放大招"""

    BaoBeiQiu = "BaoBeiQiu"
    """宝贝球"""

    Rose = "Rose"
    """玫瑰花"""

    ZhaoHuanShu = "ZhaoHuanShu"
    """召唤术"""

    RangNiPi = "RangNiPi"
    """让你皮"""

    JeiYin = "JeiYin"
    """结印"""

    ShouLei = "ShouLei"
    """手雷"""

    GouYin = "GouYin"
    """勾引"""

    ZhuaYiXia = "ZhuaYiXia"
    """抓一下"""

    SuiPing = "SuiPing"
    """碎屏"""

    QiaoMen = "QiaoMen"
    """敲门"""

    Unknown = "Unknown"
    """未知戳一戳"""

    @classmethod
    def _missing_(cls, _) -> "PokeMethods":
        return PokeMethods.Unknown


class PokeData(TypedDict):
    name: PokeMethods


@dataclass
class Poke(MessageSegment, element_type=("Poke", "poke")):
    data: PokeData = field(default_factory=dict)  # type: ignore

    def __post_init__(self):
        self.data["name"] = PokeMethods(self.data["name"])

    @override
    def __str__(self):
        return f"[戳一戳:{self.data['name']}]"


class RandomData(TypedDict):
    value: int


@dataclass
class Dice(MessageSegment, element_type=("Dice", "dice")):
    data: RandomData = field(default_factory=dict)  # type: ignore


class MusicShareKind(str, Enum):
    """音乐分享的来源。"""

    NeteaseCloudMusic = "NeteaseCloudMusic"
    """网易云音乐"""

    QQMusic = "QQMusic"
    """QQ音乐"""

    MiguMusic = "MiguMusic"
    """咪咕音乐"""

    KugouMusic = "KugouMusic"
    """酷狗音乐"""

    KuwoMusic = "KuwoMusic"
    """酷我音乐"""


class MusicShareData(TypedDict):
    kind: MusicShareKind
    title: Optional[str]
    summary: Optional[str]
    jump_url: Optional[str]
    picture_url: Optional[str]
    music_url: Optional[str]
    brief: Optional[str]


@dataclass
class Music(MessageSegment, element_type=("MusicShare", "music")):
    data: MusicShareData = field(default_factory=dict)  # type: ignore

    def __post_init__(self):
        self.data["kind"] = MusicShareKind(self.data["kind"])

    __mapping__ = {
        "kind": "kind",
        "title": "title",
        "summary": "summary",
        "jump_url": "jumpUrl",
        "picture_url": "pictureUrl",
        "music_url": "musicUrl",
        "brief": "brief",
    }

    @override
    def __str__(self):
        return "[音乐分享]"


@dataclass
class CustomNode:
    uid: int
    time: int
    name: str
    message: "Message"

    @classmethod
    def parse(cls, raw: dict):
        return cls(
            uid=raw["senderId"],
            time=raw["time"],
            name=raw["senderName"],
            message=Message.from_elements(raw["messageChain"]),
        )

    def dump(self) -> dict:
        return {
            "senderId": self.uid,
            "time": self.time,
            "senderName": self.name,
            "messageChain": self.message.to_elements(),
        }


@dataclass
class IdNode:
    id: int

    @classmethod
    def parse(cls, raw: dict):
        return cls(id=raw["messageId"])

    def dump(self) -> dict:
        return {"messageId": self.id}


class RefData(TypedDict):
    id: int
    target: Optional[int]


@dataclass
class RefNode:
    ref: RefData

    @classmethod
    def parse(cls, raw: dict):
        return cls(ref={"id": raw["messageId"], "target": raw.get("target")})

    def dump(self) -> dict:
        return {"messageRef": {"messageId": self.ref["id"], "target": self.ref.get("target")}}


class DisplayStrategy(TypedDict):
    title: Optional[str]
    """卡片顶部标题"""
    brief: Optional[str]
    """消息列表预览"""
    source: Optional[str]
    """未知"""
    preview: Optional[list[str]]
    """卡片消息预览 (只显示前 4 条)"""
    summary: Optional[str]
    """卡片底部摘要"""


class ForwardData(TypedDict):
    nodes: list[Union[CustomNode, IdNode, RefNode]]
    display_strategy: Optional[DisplayStrategy]


@dataclass
class Forward(MessageSegment, element_type=("Forward", "forward")):
    data: ForwardData = field(default_factory=dict)  # type: ignore

    __mapping__ = {"nodes": "nodeList", "display_strategy": "display"}

    def __post_init__(self):
        if "nodes" in self.data and not isinstance(self.data["nodes"][0], (CustomNode, IdNode, RefNode)):
            for index, raw in enumerate(cast(list[dict], self.data["nodes"])):
                if "messageId" in raw:
                    self.data["nodes"][index] = IdNode.parse(raw)
                elif "messageRef" in raw:
                    self.data["nodes"][index] = RefNode.parse(raw)
                else:
                    self.data["nodes"][index] = CustomNode.parse(raw)

    def dump(self) -> dict:
        return {
            **{self.__mapping__.get(k, k): v for k, v in self.data.items()},
            "nodeList": [n.dump() for n in self.data["nodes"]],
        }

    @override
    def __str__(self):
        return "[转发消息]"


class FileData(TypedDict):
    id: str
    name: str
    size: int


@dataclass
class File(MessageSegment, element_type=("File", "file")):
    data: FileData = field(default_factory=dict)  # type: ignore

    @override
    def __str__(self):
        return f"[文件:{self.data['id']}]"


class ImageData(TypedDict):
    id: Optional[str]
    url: Optional[str]
    base64: Optional[str]


@dataclass
class Image(MessageSegment, element_type=("Image", "image")):
    data: ImageData = field(default_factory=dict)  # type: ignore

    __mapping__ = {
        "id": "imageId",
    }

    @property
    def uuid(self):
        """多媒体元素的 uuid, 即元素在 mirai 内部的标识"""
        return self.data["id"].split(".")[0].strip("/{}").lower() if self.data["id"] else ""

    @override
    def __str__(self):
        return "[图片]"


@dataclass
class FlashImage(MessageSegment, element_type=("FlashImage", "flash_image")):
    data: ImageData = field(default_factory=dict)  # type: ignore

    __mapping__ = {
        "id": "imageId",
    }

    @property
    def uuid(self):
        """多媒体元素的 uuid, 即元素在 mirai 内部的标识"""
        return self.data["id"].split(".")[0].strip("/{}").lower() if self.data["id"] else ""

    @override
    def __str__(self):
        return "[闪照]"


class VoiceData(TypedDict):
    id: Optional[str]
    url: Optional[str]
    base64: Optional[str]
    length: Optional[int]


@dataclass
class Voice(MessageSegment, element_type=("Voice", "voice")):
    data: VoiceData = field(default_factory=dict)  # type: ignore

    __mapping__ = {
        "id": "voiceId",
    }

    @property
    def uuid(self):
        """多媒体元素的 uuid, 即元素在 mirai 内部的标识"""
        return self.data["id"].split(".")[0].strip("/{}").lower() if self.data["id"] else ""

    @override
    def __str__(self):
        return "[语音]"


class VideoData(TypedDict):
    id: str
    md5: str
    size: int
    format: str
    name: str
    url: str
    thumbnail: Optional[str]


@dataclass
class Video(MessageSegment, element_type=("ShortVideo", "video")):
    data: VideoData = field(default_factory=dict)  # type: ignore
    __mapping__ = {
        "id": "videoId",
        "md5": "fileMd5",
        "size": "fileSize",
        "format": "fileFormat",
        "name": "filename",
        "url": "videoUrl",
        "thumbnail": "thumbnailUrl",
    }

    @override
    def __str__(self):
        return "[短视频]"


class SourceData(TypedDict):
    id: int
    time: Optional[int]


@dataclass
class Source(MessageSegment, element_type=("Source", "source")):
    data: SourceData = field(default_factory=dict)  # type: ignore


class QuoteData(TypedDict):
    id: int
    groupId: int
    senderId: int
    targetId: int
    origin: list[dict]


@dataclass
class Quote(MessageSegment, element_type=("Quote", "quote")):
    data: QuoteData = field(default_factory=dict)  # type: ignore


TYPE_MAPPING = {cls.__element_type__[0]: cls for cls in MessageSegment.__subclasses__()}  # type: ignore


class Message(BaseMessage[MessageSegment]):
    @classmethod
    @override
    def get_segment_class(cls) -> type[MessageSegment]:
        # 返回适配器的 MessageSegment 类型本身
        return MessageSegment

    @staticmethod
    @override
    def _construct(msg: str) -> Iterable[MessageSegment]:
        yield MessageSegment.text(msg)

    @classmethod
    def from_elements(cls, elements: list[dict]) -> "Message":
        msg = Message()
        for element in elements:
            msg.append(TYPE_MAPPING[element["type"]].parse(element))
        return msg

    def to_elements(self) -> list[dict]:
        res = []
        for seg in self:
            res.append(seg.dump())
        return res
