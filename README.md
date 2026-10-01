# 🎮 SteamToNotion

> 一键将 Steam 游戏数据与高清画廊素材同步至 Notion 数据库的本地桌面工具。  
> 支持自动查重增量更新、SteamGridDB 海量艺术图选择、智能多网络环境自愈。

---

## ✨ 核心特性

- 🚀 **极速抓取与多源聚合**：输入 Steam App ID、游戏全名或商店链接，自动聚合 Steam 商店与 SteamCMD 数据（本地化译名、类型、发行日期、开发/发行商、标签、简介等）。
- 🖼️ **SteamGridDB 高清图库**：
  - **Grid 封面**：支持 **92:43 横版**（完美适配 Notion 画廊默认卡片比例）与 **600×900 竖版** 自由切换点选。
  - **Hero 横幅**：精选 1920×620 / 3840×1240 超清背景横幅，一键设为 Notion 页面 Header Cover。
  - **Icon 图标**：抓取游戏高清 Logo/客户端图标，自动设为 Notion 页面 Icon。
- 🔄 **智能查重与双模更新**：
  - 搜索游戏时自动同步检索 Notion 数据库（优先按 Steam 链接，次按名称精确匹配）。
  - 若已存在，自动回填已有数据并切换至编辑模式，提供「🖼️ 仅更新图片」与「🔄 更新全部字段」双更新策略。

---

## 🚀 快速开始

### 方式一：下载即用版（推荐，无需 Python 环境）

1. **下载程序**：
   - 前往 [Releases](https://github.com/0b110101/SteamToNotion/releases) 页面，下载最新的 `SteamToNotion-Windows.zip` 并解压到任意文件夹。
2. **准备密钥**：
   | 密钥项 | 获取途径 |
   | :--- | :--- |
   | **Notion Integration Token** *(必填)* | 访问 [Notion My Integrations](https://www.notion.so/my-integrations) → 点击「+ New integration」创建，复制 Internal Integration Secret（以 `ntn_` 或 `secret_` 开头）。 |
   | **SteamGridDB API Key** *(必填)* | 访问 [SteamGridDB Preferences API](https://www.steamgriddb.com/profile/preferences/api) 登录后生成 API Key，用于拉取高清画廊封面与横幅。 |
   | **Steam 64位 ID & Steam API Key** *(选填)* | 访问 [Steam API Key 申请页](https://steamcommunity.com/dev/apikey) 获取。**仅在需要同步「个人游玩总时长」时填写**，其余情况留空即可。<br>⚠️ *说明：受 Steam 官方 API 权限限制，游玩时长仅支持账号自己购买拥有的游戏，**无法获取家庭共享库游玩游戏的时长**。* |
   
   > ⚠️ **重要步骤（Notion 授权）**：  
   > 打开你要同步的 Notion 游戏数据库页面 → 点击右上角 `···` → `Connections (连接)` → 搜索并添加你刚才创建的 Integration。
3. **启动运行**：
   - 双击文件夹中的 `SteamToNotion.exe`；
   - 系统将自动打开默认浏览器访问 `http://127.0.0.1:8000`。
4. **初始化设置**：
   - 点击右上角 ⚙️ **设置**，填入你的 Notion Token 与 SteamGridDB Key（如需统计时长再填 Steam ID 和 Key）；
   - **网络代理设置**：若使用科学上网工具的**规则模式**，由于本地后端请求通常不走系统代理分流，**一般需要填写**本地监听端口（例如 `http://127.0.0.1:7890`）；若使用 **TUN 虚拟网卡模式**、**游戏加速器**或**直连**，留空即可；
   - 点击「加载数据库列表」选择你的游戏库，然后在下方「字段映射」表格里**手动为每个需要写入的字段选择对应的 Notion 属性列**（选择「-- 不映射 --」的字段不会被写入），确认后点击「保存所有设置」。
5. **开始录入与更新**：
   - 在搜索框中输入游戏名称或 Steam App ID（例如 `1086940` 或 `天国：拯救2`）；
   - 在下方挑选满意的封面、横幅与图标，调整标签后点击「📤 推送到 Notion」即可！

---

### 方式二：从源码运行（开发者 / 跨平台）

1. **克隆仓库**：
   ```bash
   git clone https://github.com/0b110101/SteamToNotion.git
   cd SteamToNotion
   ```

2. **安装依赖**：
   ```bash
   pip install -r requirements.txt
   ```

3. **启动后端服务**：
   ```bash
   python app.py
   ```
   启动后在浏览器打开 `http://127.0.0.1:8000` 即可开始使用。

4. **自行打包为单文件/独立目录（可选）**：
   ```bash
   python build_dist.py
   ```
   打包完成后产物位于 `dist/SteamToNotion-Windows.zip`。

---

## 📋 字段映射支持规范

| 数据项 | 数据源说明 | 推荐 Notion 属性类型 | 兼容属性类型 |
| :--- | :--- | :--- | :--- |
| **游戏名称** | 本地化名称优先（简体/繁体中文、日文、韩文等非英文名），官方只有英文名时使用英文名 | Title | Rich Text, Select |
| **全名/英文名** | 官方英文名称；**仅当「游戏名称」取到非英文的本地化名称时才填写**（官方只有英文名时不重复写入） | Rich Text | Title, Select |
| **封面 (Grid)** | SteamGridDB 精选图或 Steam 官方主封面 | Files | - |
| **横幅 (Hero)** | 页面顶部背景横幅（1920×620+） | 页面 Cover / Files | - |
| **游戏类型** | 官方分类（如：动作、角色扮演等） | Multi-select | Select, Rich Text |
| **标签 (Tags)** | 热门玩家标签（精选前 5 项或自选） | Multi-select | Select, Rich Text |
| **发行日期** | 转换为标准 ISO 格式（YYYY-MM-DD） | Date | Rich Text |
| **开发商** | 游戏开发团队 / 制作组 | Multi-select | Select, Rich Text |
| **发行商** | 游戏发行企业 | Multi-select | Select, Rich Text |
| **简介** | 官方中/英文简要描述 | Rich Text | - |
| **Steam链接** | 游戏商店主页 URL | URL | Rich Text |

---

## 📁 项目结构

```text
SteamToNotion/
├── app.py                 # FastAPI 核心后端、Steam/Notion API 路由与网络自愈层
├── build_dist.py          # Windows 独立运行包一键编译与打包脚本
├── config.example.json    # 默认配置与字段映射模板
├── requirements.txt       # Python 依赖清单
├── static/                # 前端静态资源
│   ├── index.html         # 响应式交互界面
│   ├── style.css          # 现代化黑暗主题样式
│   └── app.js             # 画廊交互、标签选择、查重编辑与数据同步逻辑
└── README.md              # 项目文档说明
```

---

## 🤝 致谢 (Acknowledgments)

本项目在开发与测试过程中得到了以下开发者与 AI 助手的支持与帮助，特此鸣谢（排名不分先后）：

- **照烧鸭腿饭**
- **SAMK**
- **Claude**
- **gemini**

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。欢迎提交 Issue 与 Pull Request！
