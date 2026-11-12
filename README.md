# twenty nice：财税 Agent 产品版

面向中小企业财税核对的对话 Agent。它能按规则版本核验发票、补全用途和备注，并查询银行流水。修改须用户确认后才保存，并留审计记录，账号按企业分权限。

## 快速开始（3 步）

**前提：** Windows 需安装 Docker Desktop（使用 Linux 容器）。Linux/macOS 需安装 Docker Engine 和 Compose v2。其他都不用装，不需要 Python、Node 或 Java。首次构建要联网拉取镜像和依赖，需要几分钟。

**第 1 步：启动。** 在仓库根目录执行：

```powershell
cd product
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Linux/macOS 执行 `cd product && ./start.sh --http`。`start.sh` 已在 Windows 上用模拟的 docker 命令检查过，尚未在真实 Linux Docker 上跑过。

首次运行时，脚本会：

- 用 `.env.example` 生成 `product/.env`：数据库等凭据填入随机值，官方评测模型地址、`qwen3.8-max` 和 `PRODUCT_CONTEXT_BUDGET=24000` 已预填；
- 构建并启动全部容器；
- 自动导入官方 v1.1.0 示例数据。

成功时最后一行是：

```text
赛题数据就绪：40 张发票、48 条流水
```

然后浏览器打开 **http://127.0.0.1:3100/**。脚本不打印网址。启动时出现 `Chat (model answers) needs PRODUCT_MODEL_API_KEY ...` 是正常的，见第 2 步。

**第 2 步：填模型 Key，再启动一次。** 用记事本打开 `product/.env`，只填写 `PRODUCT_MODEL_API_KEY=` 后面的值，其他行都不用改。然后再执行一次第 1 步的命令：数据不会重复导入，容器会按新配置重建。

- 不要先手动把 `.env.example` 复制成 `.env`：脚本只在 `.env` 不存在时生成随机凭据，手动复制会留下空的数据库密码。
- 不填 Key 也能登录、查看发票、流水和规则，只是对话得不到模型回答。

**第 3 步：登录并提问。**

| 账号 | 密码 | 权限 |
|---|---|---|
| `u001` | `Demo-u001-2026!` | 甲企业（C001）、乙企业（C002）：查看并修改用途和备注 |
| `u002` | `Demo-u002-2026!` | 只能查看甲企业；看不到乙企业，提交修改会被拒绝 |

这两个是写在 `.env.example` 中的公开演示密码，仅供本机评测。

在「对话」中选甲企业、月份 2026-09，可以先问：

1. 「甲企业2026年9月的发票合计、银行收入和银行支出分别是多少？」预期：发票合计 9,622.06，银行收入 13,000.50，银行支出 7,180.74。
2. 「2026年9月哪些发票缺少用途？」按规则 R002 2.0，应为 F002、F003、F004、F006、F009。
3. 用 `u002` 登录，尝试查看乙企业或修改甲企业，演示权限隔离。

每次模型调用约 1 分钟，期间右侧「过程与依据」显示进度。

**可选 HTTPS：** Windows 加 `-Https` 参数，需要 PATH 上有 openssl。装有 Git for Windows 时，可先执行 `$env:Path += ';C:\Program Files\Git\usr\bin'`。Linux/macOS 的 `./start.sh` 不加 `--http` 时默认就是 HTTPS。HTTPS 入口为 **https://localhost:3443/**，需先信任 `product/tls/local/ca.crt`。

### 常见问题

- **提示找不到 openssl：** 去掉 `-Https`（`start.sh` 加 `--http`），改用 HTTP；或按上文把 Git for Windows 的 `usr\bin` 加入 PATH。
- **演示密码登录失败：** 多半是之前运行过，`product/.env` 已经存在。脚本不会改写已有 `.env`，也不会重置已有账号密码，所以账号仍使用旧 `.env` 中 `PRODUCT_U001_PASSWORD`、`PRODUCT_U002_PASSWORD` 的值。要按演示密码从头开始：执行 `docker compose -p product down -v`（会**删除全部数据**），删除 `product/.env`，再从第 1 步开始。
- **首次构建慢或失败：** 需要访问 Docker Hub、PyPI、npm、Maven 等仓库。网络恢复后重新执行第 1 步即可。
- **对话慢：** 每次模型调用约 1 分钟，属正常现象。
- **端口被占用：** 设置环境变量 `PRODUCT_HTTP_PORT` 或 `PRODUCT_HTTPS_PORT` 后再启动，入口端口随之改变。

## 文档

- [产品版 README](product/README.md)：详细启动说明、配置变量、分阶段验收
- [设计说明](product/docs/设计说明.md)
- [已知限制](product/docs/已知限制.md)
- [五分钟演示脚本](product/docs/演示脚本.md)
- [数据导入说明](product/数据导入说明.md)
- [关键运行记录](关键运行记录/)
- [提交说明](提交说明.md)
