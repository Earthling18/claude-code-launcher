"""
清除指定用户的会话上下文
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def clear_user_session(user_id: str):
    """清除指定用户的会话"""
    from app.core.session_manager import session_manager

    print(f"Clearing session for user: {user_id}")

    # 启动 session_manager（如果未运行）
    if session_manager._cleanup_task is None:
        await session_manager.start()

    # 销毁会话
    success = await session_manager.destroy(user_id)

    if success:
        print(f"[OK] Session for user '{user_id}' has been cleared")
        print(f"  - Memory session data removed")
        print(f"  - Workspace directory deleted: workspace/{user_id}/")
        print(f"  - Claude conversation history cleared")
    else:
        print(f"[INFO] No active session found for user '{user_id}'")

    # 停止 session_manager
    await session_manager.stop()

    return success

async def list_active_sessions():
    """列出所有活跃会话"""
    from app.core.session_manager import session_manager

    print("\nActive sessions:")
    print("-" * 60)

    if not session_manager.sessions:
        print("No active sessions")
        return

    for user_id, session in session_manager.sessions.items():
        print(f"User ID: {user_id}")
        print(f"  Name: {session.user_name}")
        print(f"  Workspace: {session.workspace}")
        print(f"  Messages: {session.message_count}")
        print(f"  Last accessed: {session.last_accessed}")
        print(f"  Claude session: {session.claude_session_id or 'None'}")
        print()

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python clear_user_session.py <user_id>    # Clear specific user")
        print("  python clear_user_session.py --list       # List all users")
        print("\nExample:")
        print("  python clear_user_session.py yanbinmo")
        sys.exit(1)

    user_id = sys.argv[1]

    if user_id == "--list":
        asyncio.run(list_active_sessions())
    else:
        asyncio.run(clear_user_session(user_id))

if __name__ == "__main__":
    main()
