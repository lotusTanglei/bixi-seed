# 文件与 Excel 基础能力

`core/filekit` 是给后续业务模块和 AI 生成代码使用的复用边界。第一阶段只提供能力，不提供固定的导入页面、客户模块或其他业务菜单。

## 上传文件

业务接口收到 Django 的 `request.FILES["file"]` 后，使用 `store_uploaded_file` 保存文件。文件会进入 `data/uploads/<分类>/`，实际文件名使用随机 ID，返回的 `StoredUpload` 可以由业务模块保存到自己的记录中。

```python
from core.filekit import store_uploaded_file

uploaded = request.FILES.get("file")
stored = store_uploaded_file(
    uploaded,
    category="customer-import",
    allowed_extensions={".xlsx", ".xlsm"},
)
```

上传模块统一处理文件名清理、扩展名、大小、分类目录和路径边界。默认大小上限由 `BIXI_UPLOAD_MAX_BYTES` 控制，默认是 10 MB。

## 解析 Excel

`parse_excel_upload` 读取第一行作为表头，返回 `columns`、`rows` 和 `row_count`。默认读取第一个工作表，也可以传入 `sheet_name`。日期会转成 ISO 文本，公式按缓存值读取，不执行宏或任意代码。

```python
from core.filekit import parse_excel_upload

parsed = parse_excel_upload(uploaded, sheet_name="客户")
for row in parsed["rows"]:
    # 在这里映射到当前业务 Feature 的字段并进行业务校验。
    print(row)
```

当前支持 `.xlsx` 和 `.xlsm`，行数和列数分别由 `BIXI_EXCEL_MAX_ROWS`、`BIXI_EXCEL_MAX_COLUMNS` 限制。`.xls` 二进制格式暂不支持，避免在核心中引入更重的转换依赖。

## 使用边界

- 上传和解析模块不创建数据表，不绑定任何组织业务模型。
- AI 生成业务接口时必须先做当前组织权限校验，再调用 `filekit`。
- 解析出的行数据仍需经过 Feature 字段校验，不能直接写入数据库。
- 当前没有通用上传菜单和公开上传接口；具体业务的上传页面、字段映射和导入结果由后续 AI 或开发者按业务生成。
