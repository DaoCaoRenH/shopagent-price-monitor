# 参与开发

使用 Python 3.11+ 创建项目虚拟环境，安装 `pip install -e ".[dev]"`。后端位于 `src/shopagent_monitor/`；Vue 3 + TypeScript 前端位于 `frontend/`，开发需要 Node 22.12+ 或 24+，首次执行 `npm ci`。构建产物随 Python 安装包提供，普通用户不需要安装 Node。

提交前运行：

```bash
cd frontend
npm ci
npm test
npm run build
cd ..
# 使用项目虚拟环境中的 Python
python -m unittest discover -s tests -v
python -m ruff check src tests tools
python -m build
```

测试须使用临时数据库、自造商品和受控模型，不能依赖本地用户状态、外部模型 Key 或历史实验产物。价格判断与工具协议的修改应有行为测试，文档应同步说明配置或流程变化。

请先描述可复现的问题、预期行为和已有验证。提交范围保持集中；不要上传凭据、真实用户需求、数据库、第三方商品目录或模型权重。新平台取价器应实现 `PriceProvider`，并明确报价与规格的对应关系。

跨平台路径用 pathlib；状态存到 `--data-dir`，不要写入安装目录。页面负责组合，组件负责显示与输入，composables 管理异步流程，api 模块负责请求。组件与页面不直接调用 fetch。变更后提交 `frontend/` 源码与重新构建的 `app/static/`，不要手改生成文件。详细边界和竞态处理见 [前端开发说明](docs/frontend-refactor.md)。Python 单测、前端类型/行为测试与安装包资源都需要保持可用。
