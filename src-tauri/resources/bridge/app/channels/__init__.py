"""
渠道路由模块

根据 channel 字段动态返回对应渠道的 messenger 和 file_client。
"""


def get_messenger(channel: str = "wecom"):
    """获取对应渠道的消息推送器"""
    if channel == "feishu":
        from app.channels.feishu.messenger import feishu_messenger
        return feishu_messenger
    from app.services.proactive_messenger import proactive_messenger
    return proactive_messenger


def get_file_client(channel: str = "wecom"):
    """获取对应渠道的文件客户端"""
    if channel == "feishu":
        from app.channels.feishu.file_client import feishu_file_client
        return feishu_file_client
    from app.services.cos_client import cos_client
    return cos_client
