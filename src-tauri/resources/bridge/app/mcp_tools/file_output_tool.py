"""
文件输出工具

支持两种模式：
1. prompt 模式：从 Agent 回复中解析 <!--RETURN_FILES:["file.txt"]--> 格式
2. mcp 模式：使用 SDK MCP 工具标记文件（Windows 有兼容性问题）
"""
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from claude_agent_sdk import tool, create_sdk_mcp_server

logger = logging.getLogger(__name__)

# 标记文件名
OUTPUT_MARKER_FILENAME = ".output_files.json"


def _write_marker(workspace: Path, file_path: str, description: str = "") -> Dict[str, Any]:
    """写入输出标记"""
    if not workspace:
        return {"success": False, "message": "工作目录未设置"}

    marker_file = workspace / OUTPUT_MARKER_FILENAME

    try:
        # 读取现有内容
        existing = []
        if marker_file.exists():
            try:
                data = json.loads(marker_file.read_text(encoding="utf-8"))
                existing = data.get("files", []) if isinstance(data, dict) else data
            except Exception:
                pass

        # 检查是否已存在
        for item in existing:
            if item.get("file_path") == file_path:
                return {"success": True, "message": f"该文件已标记过，无需重复调用。文件将自动发送给用户: {file_path}"}

        # 追加新项
        existing.append({
            "file_path": file_path,
            "description": description,
        })

        # 写入文件
        marker_file.write_text(
            json.dumps({"files": existing}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        logger.info(f"[FileOutputTool] Marked file: {file_path}")
        return {"success": True, "message": f"已标记文件并将自动发送给用户: {file_path}。请勿对同一文件重复调用此工具。"}

    except Exception as e:
        logger.error(f"[FileOutputTool] Failed to write marker: {e}")
        return {"success": False, "message": f"标记失败: {str(e)}"}


def create_file_output_server(workspace: Path):
    """
    创建文件输出 SDK MCP 服务器

    使用闭包捕获 workspace，确保在异步上下文中可以访问

    Args:
        workspace: 工作目录路径

    Returns:
        SDK MCP 服务器配置
    """
    logger.info(f"[FileOutputTool] Creating server with workspace: {workspace}")

    # 使用闭包捕获 workspace
    captured_workspace = workspace

    @tool(
        "return_file_to_user",
        "标记一个文件返回给用户。每个需要发送给用户的文件都必须调用一次此工具。"
        "使用文件的绝对路径（必须来自 Glob/Bash 等工具的精确输出，不要手动拼写）。"
        "未通过此工具标记的文件不会被发送。",
        {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件的绝对路径"
                },
                "description": {
                    "type": "string",
                    "description": "文件的简短描述（可选）"
                }
            },
            "required": ["file_path"]
        }
    )
    async def return_file_to_user_handler(args: Dict[str, Any]) -> Dict[str, Any]:
        """标记文件为输出的工具处理函数"""
        file_path = args.get("file_path", "")
        description = args.get("description", "")

        logger.info(f"[FileOutputTool] return_file_to_user called: file_path={file_path}, workspace={captured_workspace}")

        if not file_path:
            return {
                "content": [{"type": "text", "text": "错误：file_path 参数不能为空"}],
                "is_error": True
            }

        # Git Bash 路径归一化：/c/Users/... → C:\Users\...
        p = Path(file_path)
        path_str = str(p)
        if len(path_str) >= 3 and path_str[0] == "/" and path_str[2] == "/":
            drive = path_str[1].upper()
            p = Path(f"{drive}:{path_str[2:]}")
            file_path = str(p)

        # 容错：文件不存在时去空格重试
        if not p.exists():
            no_space = p.parent / p.name.replace(" ", "")
            if no_space.exists():
                logger.warning(f"[FileOutputTool] Path corrected (spaces removed): {p.name} -> {no_space.name}")
                file_path = str(no_space)

        result = _write_marker(captured_workspace, file_path, description)

        if result["success"]:
            return {"content": [{"type": "text", "text": result["message"]}]}
        else:
            return {
                "content": [{"type": "text", "text": result["message"]}],
                "is_error": True
            }

    return create_sdk_mcp_server(
        name="file-output",
        version="1.0.0",
        tools=[return_file_to_user_handler]
    )


# 兼容性：保留 set_workspace 函数（不再需要，但保持 API 兼容）
def set_workspace(workspace: Path):
    """设置当前工作目录（已废弃，使用 create_file_output_server(workspace) 代替）"""
    logger.warning("[FileOutputTool] set_workspace is deprecated, use create_file_output_server(workspace) instead")


# 保留原有的函数供 routes.py 使用
def clear_output_marker(workspace: Path) -> bool:
    """
    清除输出标记文件

    Args:
        workspace: 工作目录

    Returns:
        是否成功
    """
    marker_file = workspace / OUTPUT_MARKER_FILENAME

    if marker_file.exists():
        try:
            marker_file.unlink()
            logger.info("[FileOutputTool] Cleared marker file")
            return True
        except Exception as e:
            logger.error(f"[FileOutputTool] Failed to clear marker: {e}")
            return False

    return True


def read_output_marker(workspace: Path) -> List[Dict[str, Any]]:
    """读取输出标记文件"""
    marker_file = workspace / OUTPUT_MARKER_FILENAME

    if not marker_file.exists():
        return []

    try:
        content = marker_file.read_text(encoding="utf-8")
        data = json.loads(content)

        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "files" in data:
            return data["files"]
        else:
            return []

    except Exception as e:
        logger.error(f"[FileOutputTool] Failed to read marker: {e}")
        return []


def get_marked_files(workspace: Path) -> List[Path]:
    """获取所有标记为输出的文件（绝对路径）"""
    markers = read_output_marker(workspace)
    result = []

    for item in markers:
        file_path_str = item.get("file_path", "")
        if not file_path_str:
            continue

        file_path = Path(file_path_str)
        if not file_path.is_absolute():
            file_path = workspace / file_path_str

        if file_path.exists():
            result.append(file_path)
        else:
            logger.warning(f"[FileOutputTool] Marked file not found: {file_path}")

    return result


def filter_files_by_marker(
    workspace: Path,
    candidate_files: List[str],
) -> List[str]:
    """
    根据标记过滤文件列表

    Args:
        workspace: 工作目录
        candidate_files: 候选文件名列表

    Returns:
        过滤后的文件名列表（只保留被标记的文件）
    """
    marked = read_output_marker(workspace)

    if not marked:
        # 没有标记 = 没有输出文件
        return []

    # 构建标记文件名集合
    marked_names = set()
    for item in marked:
        file_path_str = item.get("file_path", "")
        if not file_path_str:
            continue

        # 提取文件名
        file_path = Path(file_path_str)
        marked_names.add(file_path.name)

        # 也添加原始路径（如果是相对路径）
        if not file_path.is_absolute():
            marked_names.add(file_path_str)

    # 过滤
    return [f for f in candidate_files if f in marked_names or Path(f).name in marked_names]


# ========== Prompt 模式：从回复文本解析文件列表 ==========

# 匹配 <!--RETURN_FILES:["file1.txt", "file2.png"]--> 格式
RETURN_FILES_PATTERN = re.compile(
    r'<!--\s*RETURN_FILES\s*:\s*(\[.*?\])\s*-->',
    re.IGNORECASE | re.DOTALL
)


def parse_return_files_from_text(text: str) -> Tuple[List[str], str]:
    """
    从 Agent 回复文本中解析要返回的文件列表

    格式：<!--RETURN_FILES:["file1.txt", "file2.png"]-->

    Args:
        text: Agent 的回复文本

    Returns:
        (文件名列表, 清理后的文本)
        - 文件名列表：解析出的文件名
        - 清理后的文本：移除标记后的文本
    """
    if not text:
        return [], ""

    match = RETURN_FILES_PATTERN.search(text)
    if not match:
        return [], text

    try:
        # 解析 JSON 数组
        files_json = match.group(1)
        files = json.loads(files_json)

        if not isinstance(files, list):
            logger.warning(f"[PromptParser] RETURN_FILES is not a list: {files_json}")
            return [], text

        # 确保所有元素都是字符串
        file_names = [str(f) for f in files if f]

        # 移除标记，清理文本
        clean_text = RETURN_FILES_PATTERN.sub('', text).strip()

        logger.info(f"[PromptParser] Parsed {len(file_names)} files from response: {file_names}")
        return file_names, clean_text

    except json.JSONDecodeError as e:
        logger.warning(f"[PromptParser] Failed to parse RETURN_FILES JSON: {e}")
        return [], text
    except Exception as e:
        logger.error(f"[PromptParser] Error parsing RETURN_FILES: {e}")
        return [], text


def filter_files_by_prompt(
    candidate_files: List[str],
    marked_files: List[str],
) -> List[str]:
    """
    根据 prompt 解析的文件列表过滤候选文件

    Args:
        candidate_files: 候选文件名列表（新增/修改的文件）
        marked_files: 从 prompt 解析出的文件名列表

    Returns:
        过滤后的文件名列表
    """
    if not marked_files:
        return []

    # 构建标记文件名集合（支持只匹配文件名部分）
    marked_names = set()
    for f in marked_files:
        marked_names.add(f)
        # 如果是路径，也添加文件名部分
        marked_names.add(Path(f).name)

    # 过滤
    result = [f for f in candidate_files if f in marked_names or Path(f).name in marked_names]
    logger.info(f"[PromptParser] Filtered {len(candidate_files)} candidates to {len(result)} files")
    return result
