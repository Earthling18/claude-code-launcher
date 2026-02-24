#!/usr/bin/env python
"""
启动脚本
"""
import uvicorn
from app.config import settings

if __name__ == "__main__":
    print(f"Starting server on {settings.host}:{settings.port}")
    print(f"Debug mode: {settings.debug}")
    print(f"Skills directory: {settings.skills_dir}")
    print(f"Workspace directory: {settings.workspace_dir}")
    print()
    print("API Documentation: http://localhost:8000/docs")
    print()

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        http="httptools",  # 使用 httptools 代替 h11
    )
