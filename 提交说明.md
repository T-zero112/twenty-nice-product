# 财税 Agent 产品版 v0.2.0 提交包

源码对应 Git 提交 `0ed9434e8a849c1bd5129d711564f4bc85e98a6d`（分支 `codex/product-p8-acceptance`）。本包用 `git archive` 导出已提交的 `product/` 目录，不含未提交的竞赛版改动、本地 `.env`、TLS 私钥、数据卷和依赖缓存。

- 启动与配置：`product/README.md`（推荐在仓库解压后的 `product/` 上一级执行 `powershell -ExecutionPolicy Bypass -File product/start.ps1 -Https`）。将 `product/.env.example` 复制为 `product/.env` 并填写变量；`PRODUCT_CONTEXT_BUDGET` 推荐 24000。
- 设计说明、已知限制、五分钟演示脚本：`product/docs/`。
- 官方数据导入：`product/数据导入说明.md`。
- 关键运行记录：见本包 `关键运行记录/`。

不要把真实密钥、私钥或个人数据放进本包的任何副本。首次 HTTPS 启动会在本地生成证书，这些文件不应再打包提交。
