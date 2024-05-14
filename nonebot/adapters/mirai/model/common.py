"""Ariadne 各种 model 存放的位置"""

from datetime import datetime
from typing import Union, Literal, Optional

from pydantic import Field
from nonebot.compat import PYDANTIC_V2, type_validate_python

from .base import ModelBase
from ..compat import field_validator
from .relationship import Group, Friend


class DownloadInfo(ModelBase):
    """描述一个文件的下载信息."""

    sha: str = ""
    """文件 SHA256"""

    md5: str = ""
    """文件 MD5"""

    download_times: int = Field(..., alias="downloadTimes")
    """下载次数"""

    uploader_id: int = Field(..., alias="uploaderId")
    """上传者 QQ 号"""

    upload_time: datetime = Field(..., alias="uploadTime")
    """上传时间"""

    last_modify_time: datetime = Field(..., alias="lastModifyTime")
    """最后修改时间"""

    url: Optional[str] = None
    """下载 url"""


class Announcement(ModelBase):
    """群公告"""

    group: Group
    """公告所在的群"""

    senderId: int
    """发送者QQ号"""

    fid: str
    """公告唯一标识ID"""

    all_confirmed: bool = Field(..., alias="allConfirmed")
    """群成员是否已全部确认"""

    confirmed_members_count: int = Field(..., alias="confirmedMembersCount")
    """已确认群成员人数"""

    publication_time: datetime = Field(..., alias="publicationTime")
    """公告发布时间"""


class FileInfo(ModelBase):
    """群组文件详细信息"""

    name: str = ""
    """文件名"""

    path: str = ""
    """文件路径的字符串表示"""

    id: Optional[str] = ""
    """文件 ID"""

    parent: Optional["FileInfo"] = None
    """父文件夹的 FileInfo 对象, 没有则表示存在于根目录"""

    contact: Optional[Union[Group, Friend]] = None
    """文件所在位置 (群组)"""

    is_file: bool = Field(..., alias="isFile")
    """是否为文件"""

    is_directory: bool = Field(..., alias="isDirectory")
    """是否为目录"""

    download_info: Optional[DownloadInfo] = Field(None, alias="downloadInfo")
    """下载信息"""

    @field_validator("contact", mode="before")
    def _(cls, val: Optional[dict]):
        if not val:
            return None
        return type_validate_python(Friend, val) if "remark" in val else type_validate_python(Group, val)


if PYDANTIC_V2:
    FileInfo.model_rebuild(force=True)
else:
    FileInfo.update_forward_refs(FileInfo=FileInfo)


class Profile(ModelBase):
    """指示某个用户的个人资料"""

    nickname: str
    """昵称"""

    email: Optional[str] = None
    """电子邮件地址"""

    age: Optional[int] = None
    """年龄"""

    level: int
    """QQ 等级"""

    sign: str
    """个性签名"""

    sex: Literal["UNKNOWN", "MALE", "FEMALE"]
    """性别"""
