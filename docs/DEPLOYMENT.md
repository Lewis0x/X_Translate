# 部署指南（Deployment）

本文档面向运维 / 需要把 X_Translate 部署到服务器、团队内网或容器化环境的读者。开发者单机运行 `python webapp.py` 已在 README 中说明，这里聚焦生产化的几种常见形态：

- 单机 systemd 服务
- Nginx 反向代理（+ HTTPS）
- Docker 镜像
- CI 自动化场景

> **定位：** X_Translate 是一个面向个人 / 小团队的工具。默认配置为 `host=127.0.0.1, port=5050`，仅本机可访问。如需对外暴露，请务必先阅读 [安全注意事项](#7-安全注意事项)。

---

## 1. 运行环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | **3.10+** | 用到 PEP 604 类型语法 |
| 系统 | Linux / macOS / Windows Server | 三平台均测试通过 |
| LibreOffice | 7.x+（可选） | 启用 PDF 打印；Linux 推荐 `libreoffice-core + libreoffice-writer + libreoffice-calc + libreoffice-impress` |
| MS Office | 2016+ (Windows 可选) | 启用 Word/Excel COM 引擎；服务器上用 Office 需合法授权 |
| 中文字体 | Noto CJK / 微软雅黑 | 防止输出 PDF 出现方块 |

资源建议：
- 最小：1 vCPU / 1 GB RAM（仅翻译文本）
- 推荐：2 vCPU / 2 GB RAM（含 PDF 打印）
- 高并发（>5 同时任务）：4 vCPU / 4 GB RAM + SSD

---

## 2. 生产前必改清单

1. **关 Flask debug**：编辑 `webapp.py` 末尾，把 `debug=True` 改成 `False`，或改用下文的 gunicorn/waitress。
2. **绑定地址**：内网部署时把 `host="127.0.0.1"` 改成 `"0.0.0.0"`；在反代后建议维持 `127.0.0.1` 只让反代访问。
3. **清空示例密钥**：确认 `local.config.json` 里没有真实 key（部署包里应当只放 `local.config.sample.json`，生产机上再填）。
4. **目录权限**：`web_runs/` 与 `output/` 需要服务账号有读写权限。
5. **日志轮转**：`translator.log` 不会自动轮转；长期运行建议用 `logrotate`（Linux）或 `nssm` 包装服务并配置日志归档。

---

## 3. 使用 gunicorn / waitress 替代 `app.run`

### 3.1 Linux：gunicorn

```bash
pip install gunicorn
gunicorn -w 2 -k gthread --threads 4 \
         -b 127.0.0.1:5050 \
         --access-logfile - --error-logfile - \
         webapp:app
```

参数说明：
- `-w 2`：2 个 worker 进程。因为翻译 job 自己 fork 子进程，Flask 进程只做状态查询，不需要太多 worker。
- `-k gthread --threads 4`：每个 worker 4 线程（处理长轮询日志比较友好）。
- 日志直接 stdout/stderr，由 systemd / docker 捕获。

### 3.2 Windows：waitress

```powershell
pip install waitress
python -m waitress --host=127.0.0.1 --port=5050 webapp:app
```

> ⚠️ 不要在 Windows 用 gunicorn；那是 Unix-only。

---

## 4. systemd 服务（Linux）

`/etc/systemd/system/x-translate.service`：

```ini
[Unit]
Description=X_Translate (doc_translator)
After=network.target

[Service]
Type=simple
User=xtranslate
WorkingDirectory=/opt/x_translate
Environment="OPEN_API_KEY=sk-xxxxx"
ExecStart=/opt/x_translate/.venv/bin/gunicorn -w 2 -k gthread --threads 4 -b 127.0.0.1:5050 webapp:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now x-translate
sudo journalctl -u x-translate -f
```

---

## 5. Nginx 反向代理 + HTTPS

`/etc/nginx/sites-available/x-translate`：

```nginx
server {
    listen 443 ssl http2;
    server_name translate.example.com;

    ssl_certificate     /etc/letsencrypt/live/translate.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/translate.example.com/privkey.pem;

    # 大文件上传（与 Excel / PDF 常见尺寸匹配）
    client_max_body_size 200m;
    proxy_read_timeout   3600s;  # 长轮询日志接口
    proxy_send_timeout   3600s;

    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name translate.example.com;
    return 301 https://$host$request_uri;
}
```

---

## 6. Docker 镜像

仓库未提供官方 Dockerfile，下方示例可直接 `docker build`：

```dockerfile
# Dockerfile
FROM python:3.11-slim

# LibreOffice + 中文字体
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress \
        fonts-noto-cjk \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

EXPOSE 5050
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "4", \
     "-b", "0.0.0.0:5050", "webapp:app"]
```

构建与运行：

```bash
docker build -t x-translate:latest .
docker run -d --name x-translate \
  -p 5050:5050 \
  -v $(pwd)/web_runs:/app/web_runs \
  -v $(pwd)/local.config.json:/app/local.config.json:ro \
  x-translate:latest
```

说明：
- 把 `web_runs/` 挂到宿主机保留任务历史；
- `local.config.json` 以只读方式挂载，避免容器内误写；
- 不内置 MS Office，因此 Windows COM 引擎仅在宿主 Windows 部署时可用。

### docker-compose 示例

```yaml
services:
  x-translate:
    build: .
    container_name: x-translate
    ports:
      - "127.0.0.1:5050:5050"
    volumes:
      - ./web_runs:/app/web_runs
      - ./local.config.json:/app/local.config.json:ro
    environment:
      - TZ=Asia/Shanghai
    restart: unless-stopped
```

---

## 7. 安全注意事项

1. **API Key 保护**：绝对不要把 `local.config.json` 打进公共镜像；使用环境变量或挂载 secret。
2. **认证**：`webapp.py` 本身 **不做身份认证**。如果要公网访问，**必须**在反代层加 Basic Auth / OAuth2 / IP allowlist；否则任何人都能用你的 API Key 翻译。
3. **文件限额**：反代层限制 `client_max_body_size`；业务层可在 `/api/jobs` 前置检查文件大小。
4. **任务清理**：`web_runs/` 会持续累积，建议 cron 定期删除 >N 天前的 job 目录（保留 `job_state.json` 作审计）。
5. **隔离渲染引擎**：LibreOffice 处理不可信文档时有风险（宏、嵌入脚本）。生产上：
   - 配置 `soffice` 的 `-env:UserInstallation=` 到隔离目录；
   - 或用 Docker 容器完全隔离。
6. **日志脱敏**：`translator.log` 记录了请求/响应摘要；如果翻译内容敏感，把日志目录单独挂盘并限制访问。

---

## 8. 监控与健康检查

### 健康检查端点

项目未提供独立 `/health`，但下列请求可用于探活：

```bash
# 1) 主页返回 200 表示 Flask 进程正常
curl -sf http://127.0.0.1:5050/ >/dev/null && echo ok

# 2) PDF 引擎就绪
curl -s http://127.0.0.1:5050/api/pdf/engine | jq .available
```

### 指标采集

- gunicorn + `prometheus_flask_exporter`：暴露 `/metrics`。
- 业务层可关注：`/api/jobs` 平均时长、`job_state.json` 中 `failed` 数、PDF 引擎可用状态。

---

## 9. CI 场景

在 CI 中一般只做翻译 + PDF 的 smoke：

```yaml
# GitHub Actions 示例（节选）
- name: Install deps
  run: |
    sudo apt-get update
    sudo apt-get install -y libreoffice-core libreoffice-writer fonts-noto-cjk
    pip install -r requirements.txt
- name: Import check
  run: python -c "import webapp"
- name: Run pytest
  run: python -m pytest tests/ -v
- name: Smoke PDF engine
  run: |
    python -m doc_translator.print_pdf_cli --help
    python -m doc_translator.print_pdf_cli -i tests -o /tmp/out --dry-run
```

参考 `.github/workflows/ci.yml`，以及 [tests/README.md § 5](../tests/README.md#5-ci)。

---

## 10. 升级 / 回滚

### 升级

```bash
cd /opt/x_translate
git fetch && git checkout v<new-tag>
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart x-translate
```

**建议：** 先 `systemctl stop`，让当前任务跑完（`/api/jobs/<id>` 看状态），再升级；正在运行的 worker 子进程不会被主进程升级打断，但新请求会被拒绝直到重启完成。

### 回滚

```bash
git checkout v<old-tag>
pip install -r requirements.txt
sudo systemctl restart x-translate
```

`web_runs/` 目录结构在各版本间向后兼容；不必迁移数据。

---

## 11. 相关文档

- [README.md](../README.md) — 用户使用说明
- [ARCHITECTURE.md](ARCHITECTURE.md) — 进程模型与模块分层
- [API.md](API.md) — HTTP 接口规范
- [PDF_PRINTING.md](PDF_PRINTING.md) — PDF 引擎安装详解
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — 常见错误排查
