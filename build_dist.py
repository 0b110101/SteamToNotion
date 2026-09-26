import os
import sys
import json
import shutil
import subprocess
from pathlib import Path

def build():
    root = Path(__file__).parent.resolve()
    static_dir = root / "static"
    app_py = root / "app.py"
    dist_dir = root / "dist"
    app_dist_dir = dist_dir / "SteamToNotion"
    config_src = root / "config.json"
    
    # 静态文件夹路径拼接为 PyInstaller 格式: source;dest
    add_data_arg = f"{static_dir};static"
    
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",                       # 单一目录绿色便携版（秒启动，兼容性最高）
        "--clean",
        "--name", "SteamToNotion",
        f"--add-data={add_data_arg}",
        "--collect-all", "uvicorn",
        "--collect-all", "fastapi",
        "--collect-all", "starlette",
        "--collect-all", "httpx",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespans",
        "--hidden-import=uvicorn.lifespans.on",
        str(app_py)
    ]
    
    print("Executing build command:")
    print(" ".join(cmd))
    res = subprocess.run(cmd, cwd=str(root))
    if res.returncode != 0:
        print(f"\n[ERROR] Build failed with exit code: {res.returncode}")
        return

    print("\n[SUCCESS] PyInstaller build completed successfully!")
    
    # 1. 生成纯净配置模板（绝对不打包私有密钥，保护隐私安全）
    clean_config = {
        "notion_token": "",
        "steamgriddb_key": "",
        "steam_api_key": "",
        "steam_id64": "",
        "database_id": "",
        "proxy": "",
        "field_mapping": {
            "title": {"name": "游戏名称", "type": "title", "enabled": True},
            "title_en": {"name": "全名", "type": "rich_text", "enabled": True},
            "cover_grid": {"name": "封面", "type": "files", "enabled": True},
            "genre": {"name": "类型", "type": "multi_select", "enabled": True},
            "tags": {"name": "标签", "type": "multi_select", "enabled": True},
            "release_date": {"name": "发行日期", "type": "date", "enabled": True},
            "playtime": {"name": "游玩时长", "type": "number", "enabled": True},
            "developer": {"name": "开发商", "type": "multi_select", "enabled": True},
            "publisher": {"name": "发行商", "type": "multi_select", "enabled": True},
            "description": {"name": "简介", "type": "rich_text", "enabled": True},
            "steam_url": {"name": "Steam链接", "type": "url", "enabled": True}
        },
        "use_hero_as_cover": True,
        "use_icon_as_page_icon": True
    }
    target_config = app_dist_dir / "config.json"
    with open(target_config, "w", encoding="utf-8") as f:
        json.dump(clean_config, f, indent=2, ensure_ascii=False)
    print(f"[CONFIG] Generated clean template config.json -> {target_config}")

    # 2. 生成小白友好的使用说明
    readme_path = app_dist_dir / "使用说明.txt"
    readme_content = """【Steam to Notion 快捷使用说明】

1. 请先解压！
   请务必将本压缩包【全部解压】到一个普通文件夹（例如桌面、D盘等），不要直接在压缩包内双击运行。

2. 启动程序：
   双击运行「SteamToNotion.exe」，程序启动后会自动在浏览器中打开主界面 (http://127.0.0.1:8000)。

3. 关于 API 密钥与配置持久化：
   - 所有的设置（包括 Notion Token、SteamGridDB 密钥、数据库选择、标签映射等）均保存在同目录下的「config.json」中。
   - 只要本目录下的「config.json」存在，你保存的密钥和配置就会一直生效。
   - 如果要将配置分享给朋友或备份，只需保留好「config.json」即可。

4. 退出程序：
   直接关闭黑色的控制台黑框即可完全退出。
"""
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"[README] Created {readme_path}")

    # 3. 自动生成 Windows 便携发布压缩包
    zip_base = dist_dir / "SteamToNotion-Windows"
    zip_file = dist_dir / "SteamToNotion-Windows.zip"
    if zip_file.exists():
        try:
            zip_file.unlink()
        except Exception as e:
            print(f"[WARN] Could not remove old zip: {e}")

    print(f"[ZIP] Creating archive: {zip_file}...")
    shutil.make_archive(
        base_name=str(zip_base),
        format="zip",
        root_dir=str(dist_dir),
        base_dir="SteamToNotion"
    )
    print(f"[SUCCESS] Standalone package ready at: {zip_file}")
    print(f"Output directory: {app_dist_dir}")

if __name__ == "__main__":
    build()
