# 电子阅览室规章制度 阅读器（Windows + PySide6）

本程序启动后将窗口置顶并屏幕居中，强制阅读 5 秒：
- 5 秒内：
  - 窗口保持最前。
  - 鼠标被固定在屏幕中心（每 10ms 复位一次）。
  - 全局键盘按键被拦截（低级键盘钩子）。
  - 不允许关闭窗口。
- 5 秒后：
  - 自动解除限制，按钮变为可用，可手动关闭。

注意：
- 该程序仅限 Windows 使用（通过 WinAPI 实现键盘与鼠标限制）。
- 出于安全考虑，本程序未使用 `ClipCursor` 全局裁剪方式，改为高频率 `SetCursorPos` 将光标拉回中心，程序退出后不会残留系统状态。

## 运行步骤（PowerShell）

```powershell
# 在项目根目录下
cd d:\coding\glzx-lib\glzx-lib\reading_app

# 建议使用虚拟环境（可选）
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt

# 运行
python .\main.py
```

## CI 打包为 EXE（GitHub Actions）

仓库内已提供工作流：`.github/workflows/build-exe.yml`

- 触发方式：
  - 手动：在 GitHub 仓库的 Actions 标签页中选择 “Build Windows EXE (PyInstaller)” 并点击 “Run workflow”。
  - 自动：当对 `reading_app/**` 目录有提交到 `main`/`master`，或对该工作流文件自身的改动时自动触发。
- 构建环境：Windows（windows-latest）、Python 3.11、PyInstaller 单文件打包、隐藏控制台窗口（`--windowed`）。
- 资源文件：已自动将 `reading_app/config.json` 与 `reading_app/rules.md` 打包到可执行文件中，程序可在打包环境正常读取。
- 构建产物：
  - 在 Actions 的运行详情页 “Artifacts” 中下载 `reading_app-windows-exe`，内含 `dist/reading_app.exe`。

如需自定义图标、名称或包含更多数据文件，可修改工作流中的 PyInstaller 命令，例如：

```
pyinstaller --name "your_app" --onefile --windowed \
  --icon "path/to/icon.ico" \
  --add-data "reading_app/extra.dat;." reading_app/main.py
```

## 可调参数
- `lock_seconds`: 默认 5，可在 `main.py` 中 `ReadWindow(lock_seconds=5)` 调整。

## 已知限制
- 极少数系统快捷键（如 Win+L）可能无法被完全屏蔽，通常不影响 5 秒阅读完成。
- 多显示器环境下，鼠标会被拉回主屏中心。

## 卸载/退出异常情况
- 若遇到异常导致程序卡住，结束进程即可；由于未使用全局裁剪，鼠标不会被永久锁定。
