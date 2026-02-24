"""
query_info 解析器

解析企业微信传入的 query_info JSON 字符串，
提取文本内容和文件列表
"""
import json
import logging
from pathlib import Path
from typing import List, Optional, NamedTuple, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class QueryItem:
    """查询项"""
    type: str  # text | file | image
    content: str


@dataclass
class ParsedQuery:
    """解析后的查询"""
    text: str  # 合并后的文本内容
    files: List[QueryItem]  # 文件列表（file 和 image 类型）
    has_text_item: bool = False  # 是否包含 type=text 的 item（用于判断是否需要调用 SDK）
    history_list: Optional[str] = None  # 原始 history_list JSON（群聊上下文注入用）


def parse_query_info(
    query: str,
    query_info,  # 可以是 str、list 或 dict
    history_list: Optional[str] = None,  # 对话历史 JSON
) -> ParsedQuery:
    """
    解析 query_info，提取文本和文件

    企微的 query_info 格式:
    [
        {"type": "text", "content": "用户文本"},
        {"type": "file", "content": "cos://bucket/path/file.xlsx"},
        {"type": "image", "content": "cos://bucket/path/image.png"}
    ]

    注意: 用户的文本和文件可能分两条消息进入
    支持 query_info 为 JSON 字符串或已解析的 list/dict

    Args:
        query: 原始 query 字段
        query_info: query_info JSON 字符串，或已解析的 list/dict
        history_list: 对话历史 JSON，用于关联分离的消息

    Returns:
        ParsedQuery 包含合并的文本和文件列表
    """
    logger.debug(f"[PARSE] query_len={len(query) if query else 0}, query_info={'str:'+str(len(query_info)) if isinstance(query_info, str) else type(query_info).__name__ if query_info else 'None'}")

    text_parts: List[str] = []
    files: List[QueryItem] = []
    has_text_item: bool = False  # 标记是否有 type=text 的 item

    # 添加 query 字段中的文本（如果有）
    # 注意：跳过看起来像 JSON 的内容（避免重复添加 query_info 的内容）
    if query and query.strip():
        query_stripped = query.strip()
        # 如果 query 是 JSON 格式（以 [ 或 { 开头），跳过它
        if not (query_stripped.startswith('[') or query_stripped.startswith('{')):
            text_parts.append(query_stripped)
        else:
            logger.debug(f"[PARSE] Skipped JSON-like query")

    # 解析 query_info
    if query_info:
        try:
            # 兼容字符串和已解析对象
            if isinstance(query_info, str):
                items = json.loads(query_info)
            elif isinstance(query_info, (list, dict)):
                items = query_info
            else:
                items = None
                logger.warning(f"[PARSE] Unexpected query_info type: {type(query_info)}")

            if isinstance(items, list):
                for idx, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue

                    # 兼容 "type" 和 "message_type" 字段
                    item_type = item.get("type") or item.get("message_type", "")
                    # 兼容多种内容字段：content, message_content, file_id, message_file
                    content = (
                        item.get("content")
                        or item.get("message_content")
                        or item.get("file_id")
                        or item.get("message_file")  # 企业微信图片消息使用此字段
                        or ""
                    )

                    if not content:
                        continue

                    if item_type == "text":
                        # 文本类型，加入文本列表
                        has_text_item = True  # 标记有 text item
                        # 避免重复添加（query 字段可能已包含）
                        if content.strip() and content.strip() not in text_parts:
                            text_parts.append(content.strip())
                    elif item_type in ("file", "image"):
                        # 文件或图片类型
                        files.append(QueryItem(type=item_type, content=content))
                    elif item_type == "combined":
                        # 组合类型：包含多个子项（图片+文本）
                        try:
                            sub_items = json.loads(content) if isinstance(content, str) else content

                            for sub_idx, sub_item in enumerate(sub_items):
                                if not isinstance(sub_item, dict):
                                    continue

                                sub_type = sub_item.get("message_type", "")
                                sub_content = (
                                    sub_item.get("message_content")
                                    or sub_item.get("file_id")
                                    or sub_item.get("message_file")  # 企业微信图片消息使用此字段
                                    or ""
                                )

                                if not sub_content:
                                    continue

                                if sub_type == "text":
                                    has_text_item = True
                                    if sub_content.strip() and sub_content.strip() not in text_parts:
                                        text_parts.append(sub_content.strip())
                                elif sub_type in ("image", "file"):
                                    files.append(QueryItem(type=sub_type, content=sub_content))
                        except json.JSONDecodeError as e:
                            logger.error(f"[PARSE] Failed to parse combined content: {e}")
                        except Exception as e:
                            logger.error(f"[PARSE] Error processing combined type: {e}")
                    else:
                        logger.debug(f"[PARSE] Unknown type '{item_type}'")

        except json.JSONDecodeError as e:
            logger.error(f"[PARSE] Failed to parse query_info JSON: {e}")
            logger.error(f"[PARSE] Problematic JSON: {query_info[:500] if isinstance(query_info, str) else repr(query_info)[:500]}")
        except Exception as e:
            logger.error(f"[PARSE] Error processing query_info: {e}")
            import traceback
            logger.error(f"[PARSE] Traceback: {traceback.format_exc()}")

    # 合并文本
    combined_text = "\n".join(text_parts) if text_parts else ""

    # 如果当前消息主要是文件（文本很少或为空），尝试从 history 获取上下文
    if files and (not combined_text or len(combined_text.strip()) < 10):
        history_context = extract_history_context(history_list, max_items=2)
        if history_context:
            logger.debug(f"[PARSE] Added history context for file-heavy request")
            combined_text = history_context + "\n" + combined_text

    logger.debug(f"[PARSE] Result: text_len={len(combined_text)}, files={len(files)}, has_text_item={has_text_item}")

    # 构建初始 ParsedQuery
    parsed = ParsedQuery(text=combined_text, files=files, has_text_item=has_text_item, history_list=history_list)

    # 从 history 中智能关联文件或提问
    parsed = extract_related_context_from_history(parsed, history_list, max_lookback=5)

    return parsed


def extract_history_context(history_list: Optional[str], max_items: int = 3) -> str:
    """
    从 history_list 中提取最近的对话历史

    Args:
        history_list: JSON 字符串，格式：[{"role": "user", "content": "..."}, ...]
        max_items: 最多提取多少条历史消息

    Returns:
        格式化的历史上下文文本
    """
    if not history_list:
        return ""

    try:
        if isinstance(history_list, str):
            history = json.loads(history_list)
        else:
            history = history_list

        if not isinstance(history, list) or not history:
            return ""

        # 取最近的 N 条消息
        recent_history = history[-max_items:] if len(history) > max_items else history

        lines = []
        for msg in recent_history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                lines.append(f"[{role}] {content}")

        if lines:
            return "\n".join(["[对话历史]"] + lines + [""])

    except Exception as e:
        logger.warning(f"Failed to parse history_list: {e}")

    return ""


def format_group_chat_history(
    history_list: Optional[str],
    since_time: Optional[str] = None,
    max_messages: int = 15,
    max_chars: int = 3000,
) -> Tuple[str, Optional[str]]:
    """
    格式化群聊历史为可读的对话上下文

    用于群聊场景：Agent 只在 @mention 时收到请求，两次 @mention 之间的
    群聊消息对 Agent 不可见。此函数将 history_list 格式化后注入 prompt，
    让 Agent 能看到群聊的近期对话上下文。

    Args:
        history_list: JSON 字符串或已解析的 list，企微群聊消息历史
        since_time: 截止时间（格式 YYYYMMDDHHmmss），只返回此时间之后的消息
        max_messages: 最多返回的消息条数
        max_chars: 格式化后的最大字符数

    Returns:
        (格式化的历史文本, 最后一条消息的时间戳)
        如果没有可用历史，返回 ("", None)
    """
    if not history_list:
        return "", None

    try:
        if isinstance(history_list, str):
            history = json.loads(history_list)
        elif isinstance(history_list, list):
            history = history_list
        else:
            return "", None

        if not isinstance(history, list) or not history:
            return "", None

        # 过滤消息
        filtered = []
        for msg in history:
            if not isinstance(msg, dict):
                continue

            # 跳过非文本消息（系统消息、事件通知等）
            msg_type = msg.get("message_type") or msg.get("type", "")
            if msg_type and msg_type not in ("text", "combined", "file", "image"):
                continue

            # 按 since_time 过滤（去重：只保留上次注入之后的新消息）
            msg_time = msg.get("message_time", "")
            if since_time and msg_time and msg_time <= since_time:
                continue

            filtered.append(msg)

        if not filtered:
            return "", None

        # 取最近 N 条
        recent = filtered[-max_messages:] if len(filtered) > max_messages else filtered

        # 格式化消息
        lines = []
        latest_time = None

        for msg in recent:
            sender = msg.get("user_name") or msg.get("sender_name") or msg.get("user_id", "?")
            msg_time = msg.get("message_time", "")
            content = msg.get("message_content") or msg.get("content", "")
            msg_type = msg.get("message_type") or msg.get("type", "")

            # 格式化时间（YYYYMMDDHHmmss → HH:MM）
            time_str = ""
            if msg_time and len(msg_time) >= 12:
                try:
                    time_str = f"{msg_time[8:10]}:{msg_time[10:12]}"
                except (IndexError, ValueError):
                    pass

            # 构建消息行
            if msg_type in ("file", "image"):
                file_name = msg.get("message_file") or content
                if file_name:
                    # 提取文件名
                    file_display = file_name.split("/")[-1] if "/" in file_name else file_name
                    line = f"[{time_str} {sender}] [{'图片' if msg_type == 'image' else '文件'}: {file_display}]"
                else:
                    line = f"[{time_str} {sender}] [{'图片' if msg_type == 'image' else '文件'}]"
            elif content:
                # 截断过长的单条消息
                if len(content) > 200:
                    content = content[:200] + "..."
                line = f"[{time_str} {sender}] {content}"
            else:
                continue

            lines.append(line)

            # 更新最新时间戳
            if msg_time:
                latest_time = msg_time

            # 处理引用消息
            ref_info = msg.get("reference_info")
            if ref_info:
                ref_text = ref_info if isinstance(ref_info, str) else str(ref_info)
                if len(ref_text) > 100:
                    ref_text = ref_text[:100] + "..."
                lines.append(f"  > 引用: {ref_text}")

        if not lines:
            return "", None

        # 字符数限制：从前面截断
        total = 0
        start_idx = len(lines)
        for i in range(len(lines) - 1, -1, -1):
            total += len(lines[i]) + 1  # +1 for newline
            if total > max_chars:
                break
            start_idx = i
        lines = lines[start_idx:]

        if not lines:
            return "", None

        # 组装最终文本
        header = "[群聊上下文 - 续]" if since_time else "[群聊上下文 - 最近的群内对话]"
        result = header + "\n" + "\n".join(lines) + "\n---"

        logger.debug(f"[GROUP_HISTORY] Formatted {len(lines)} messages")
        return result, latest_time

    except json.JSONDecodeError as e:
        logger.warning(f"[GROUP_HISTORY] Failed to parse history_list JSON: {e}")
        return "", None
    except Exception as e:
        logger.warning(f"[GROUP_HISTORY] Error formatting group chat history: {e}")
        return "", None


def extract_related_context_from_history(
    parsed: ParsedQuery,
    history_list: Optional[str],
    max_lookback: int = 3
) -> ParsedQuery:
    """
    从 history_list 中智能提取关联的文件或提问

    场景1：当前有文件但没有文本 → 从history找最近的用户提问
    场景2：当前有文本但没有文件 → 从history找最近的用户文件

    Args:
        parsed: 当前消息的解析结果
        history_list: JSON格式的对话历史
        max_lookback: 最多回溯多少条消息

    Returns:
        增强后的 ParsedQuery 对象
    """
    if not history_list:
        return parsed

    try:
        if isinstance(history_list, str):
            history = json.loads(history_list)
        else:
            history = history_list

        if not isinstance(history, list) or not history:
            return parsed

        # 只看最近的N条消息（从后往前）
        recent_history = history[-max_lookback:] if len(history) > max_lookback else history

        has_files = len(parsed.files) > 0
        has_text = parsed.has_text_item

        # 场景1：当前有文件但没有文本 → 走缓存分支
        # 重要：不要在这里自动关联历史问题！这会破坏 RequestQueue 的缓存机制
        # 纯文件请求应该进入 process_file_only_request 分支，缓存文件等待后续文本请求
        if has_files and not has_text:
            logger.debug("[HISTORY_LINK] File-only request, handled by cache")
            # 不做任何处理，让 routes.py 走 process_file_only_request 分支

        # 场景2：当前有文本但没有文件 → 找最近的用户文件
        # 作为 RequestQueue 缓存机制的备份，防止竞态条件导致文件未被缓存
        # 只查找最近 60 秒内的文件，避免关联太旧的文件
        elif has_text and not has_files:
            logger.debug("[HISTORY_LINK] Looking for recent user files in history...")

            # 解析当前消息时间（如果有）用于时间比较
            from datetime import datetime
            current_time = None
            try:
                # 尝试从 parsed.text 相关的时间获取（这里简化处理，直接用当前时间）
                current_time = datetime.now()
            except:
                pass

            # 从后往前找最近的用户文件消息
            for msg in reversed(recent_history):
                if msg.get("user_role") == "user":
                    message_file = msg.get("message_file", "")
                    message_type = msg.get("message_type", "")

                    if message_file or message_type in ("file", "image"):
                        # 检查消息时间，只关联最近 60 秒内的文件
                        msg_time_str = msg.get("message_time", "")
                        if msg_time_str and current_time:
                            try:
                                # 格式: YYYYMMDDHHmmss
                                msg_time = datetime.strptime(msg_time_str, "%Y%m%d%H%M%S")
                                time_diff = (current_time - msg_time).total_seconds()
                                if time_diff > 120:  # 超过 2 分钟的文件不关联
                                    logger.debug(f"[HISTORY_LINK] File too old ({time_diff:.0f}s), skip")
                                    continue
                            except:
                                pass  # 时间解析失败则不做时间限制

                        # 找到文件
                        file_path = message_file if message_file else msg.get("message_content", "")
                        if file_path:
                            logger.info(f"[HISTORY_LINK] Found file: {file_path}")
                            # 添加到文件列表
                            parsed.files.append(QueryItem(
                                type="file" if message_type == "file" else "image",
                                content=file_path
                            ))
                            break

    except Exception as e:
        logger.warning(f"[HISTORY_LINK] Failed to extract context from history: {e}")

    return parsed


def build_file_context(files: List[QueryItem], workspace: str) -> str:
    """
    构建详细的文件上下文提示，帮助 Claude 理解用户的文件引用

    改进点：
    1. 为每个文件提供详细信息（类型、大小、路径）
    2. 单文件时明确指出"这就是用户提到的文件"
    3. 多文件时提供编号，方便用户引用
    4. 添加文件类型识别提示

    Args:
        files: 文件列表
        workspace: 工作目录路径

    Returns:
        文件上下文描述文本
    """
    if not files:
        return ""

    workspace_path = Path(workspace)
    lines = []

    # 标题
    if len(files) == 1:
        lines.append("[文件信息] 用户上传了1个文件：")
    else:
        lines.append(f"[文件信息] 用户上传了{len(files)}个文件：")

    lines.append("")

    # 文件类型映射
    file_type_map = {
        "xlsx": "Excel表格",
        "xls": "Excel表格",
        "csv": "CSV数据文件",
        "pdf": "PDF文档",
        "docx": "Word文档",
        "doc": "Word文档",
        "pptx": "PowerPoint演示文稿",
        "ppt": "PowerPoint演示文稿",
        "txt": "文本文件",
        "md": "Markdown文档",
        "png": "PNG图片",
        "jpg": "JPG图片",
        "jpeg": "JPG图片",
        "gif": "GIF图片",
        "json": "JSON数据文件",
        "xml": "XML文件",
        "html": "HTML文件",
    }

    # 详细文件信息
    first_file_path = None  # 用于多文件场景的示例

    for i, f in enumerate(files, 1):
        # 判断是本地路径还是 COS 路径
        if Path(f.content).is_absolute():
            # 已经是本地绝对路径（来自缓存）
            local_path = Path(f.content)
            filename = local_path.name
        else:
            # COS 路径（来自新上传）
            filename = f.content.split("/")[-1] if "/" in f.content else f.content
            local_path = workspace_path / filename

        # 保存第一个文件路径用于示例
        if i == 1:
            first_file_path = local_path

        # 文件类型识别
        file_ext = filename.split(".")[-1].lower() if "." in filename else "unknown"
        file_type_hint = file_type_map.get(file_ext, "文件")

        # 文件大小（如果已下载）
        size_info = ""
        if local_path.exists():
            size_bytes = local_path.stat().st_size
            if size_bytes < 1024:
                size_info = f" ({size_bytes} bytes)"
            elif size_bytes < 1024 * 1024:
                size_info = f" ({size_bytes / 1024:.1f} KB)"
            else:
                size_info = f" ({size_bytes / (1024 * 1024):.1f} MB)"

        # 构建文件条目
        if len(files) == 1:
            # 单文件：强调这就是用户提到的文件
            lines.append(f"- 文件名: {filename}")
            lines.append(f"  类型: {file_type_hint}{size_info}")
            lines.append(f"  完整路径: {local_path}")
            lines.append("")
            lines.append(f"【重要】 使用 Read 工具时，必须使用上述完整路径：")
            lines.append(f"    Read(file_path=r'{local_path}')")
            lines.append("")
            lines.append("注意: 当用户说'这个文件''该文件'时, 指的就是这个文件。")
        else:
            # 多文件：提供编号
            lines.append(f"[{i}] {filename}")
            lines.append(f"    类型: {file_type_hint}{size_info}")
            lines.append(f"    完整路径: {local_path}")
            lines.append("")

    if len(files) > 1:
        lines.append(f"【重要】 使用 Read 工具时，必须使用上述完整路径，例如：")
        lines.append(f"    Read(file_path=r'{first_file_path}')")
        lines.append("")
        lines.append("注意:")
        lines.append("- 当用户说'第一个文件''第二个文件'时, 按上述编号[1]、[2]对应")
        lines.append("- 当用户说'这些文件''所有文件'时, 指所有上传的文件")
        lines.append("- 当用户说'Excel文件''图片'等类型时, 从上述列表中筛选对应类型")
        lines.append("")

    lines.append(f"工作目录: {workspace_path}")

    return "\n".join(lines)


async def ensure_history_files_downloaded(
    parsed: ParsedQuery,
    workspace: Path,
    user_token: Optional[str],
    max_wait_seconds: int = 10
) -> ParsedQuery:
    """
    检查 parsed.files 中的文件是否已下载到 workspace
    如果未下载，触发下载并等待完成

    解决竞态问题：用户快速发送"文件 → 提问"时，文件可能还在下载中

    Args:
        parsed: 包含文件列表的 ParsedQuery
        workspace: 工作目录
        user_token: COS 下载需要的 token
        max_wait_seconds: 最多等待时间（秒）

    Returns:
        更新后的 ParsedQuery（移除下载失败的文件）
    """
    if not parsed.files:
        return parsed

    # 动态导入以避免循环依赖
    from app.services.cos_client import cos_client

    validated_files = []

    for file_item in parsed.files:
        cos_path = file_item.content
        filename = cos_path.split("/")[-1] if "/" in cos_path else cos_path
        local_path = workspace / filename

        # 检查文件是否已存在
        if local_path.exists():
            logger.debug(f"[FILE_WAIT] Exists: {filename}")
            validated_files.append(file_item)
            continue

        # 文件不存在，需要下载
        logger.debug(f"[FILE_WAIT] Downloading: {filename}")

        if not user_token:
            logger.error(f"[FILE_WAIT] Cannot download {filename} without user_token")
            continue

        # 触发下载
        success = await cos_client.download_file(cos_path, local_path, user_token)

        if success:
            logger.debug(f"[FILE_WAIT] Downloaded: {filename}")
            validated_files.append(file_item)
        else:
            logger.warning(f"[FILE_WAIT] Failed to download: {filename}")

    # 更新文件列表（只保留成功的）
    parsed.files = validated_files

    if len(validated_files) < len(parsed.files):
        logger.warning(f"[FILE_WAIT] Some files failed to download: {len(validated_files)}/{len(parsed.files)}")

    return parsed
