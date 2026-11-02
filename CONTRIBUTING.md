# 参与开发

使用 Python 3.11+ 创建项目虚拟环境，安装 `pip install -e ".[dev]"`。代码位于 `src/shopagent_monitor/`，前端是同源的静态文件，不需要 npm 构建。

提交前运行：

```bash
python -m unittest discover -s tests -v
python -m ruff check src tests tools
node --check src/shopagent_monitor/app/static/app.js
python -m build
```

测试须使用临时数据库、自造商品和受控模型，不能依赖本地用户状态、外部模型 Key 或历史实验产物。价格判断与工具协议的修改应有行为测试，文档应同步说明配置或流程变化。

请先描述可复现的问题、预期行为和已有验证。提交范围保持集中；不要上传凭据、真实用户需求、数据库、第三方商品目录或模型权重。新平台取价器应实现 `PriceProvider`，并明确报价与规格的对应关系。

跨平台路径用 pathlib；状态存到 `--data-dir`，不要写入安装目录。Python 单测、静态前端语法与安装包资源都需要保持可用。
