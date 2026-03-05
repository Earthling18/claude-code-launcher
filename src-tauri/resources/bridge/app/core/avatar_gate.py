"""
响应门控 - Per-session 生命周期

追踪当前对话轮次中是否有 Skill 调用。
门控关闭时，ProgressPusher 中的消息缓冲但不推送；
门控打开后（检测到 Skill 调用），缓冲的消息立即释放。
轮次结束时若门控仍关闭，丢弃缓冲消息。
"""
import logging

logger = logging.getLogger(__name__)


class AvatarGate:
    """
    响应门控

    - auto 模式：门控始终打开，所有消息正常推送
    - semi 模式：门控默认关闭，检测到 Skill 调用后打开
    """

    def __init__(self, is_semi_auto: bool):
        self.is_semi_auto = is_semi_auto
        self._skill_invoked = False

    @property
    def should_respond(self) -> bool:
        """是否应该推送消息"""
        return (not self.is_semi_auto) or self._skill_invoked

    def on_skill_invoked(self, skill_name: str):
        """
        检测到 Skill 调用时触发

        Args:
            skill_name: 被调用的 Skill 名称
        """
        self._skill_invoked = True
        logger.info(f"[GATE] Skill invoked: '{skill_name}', gate opened")

    def reset_round(self):
        """
        轮次结束（ResultMessage）后重置，为下一轮做准备
        """
        was_invoked = self._skill_invoked
        self._skill_invoked = False
        if self.is_semi_auto:
            logger.debug(
                f"[GATE] Round reset (was_skill_invoked={was_invoked})"
            )
