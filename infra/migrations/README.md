# Database Migrations

当前已经接入 Alembic。

常用命令：

```bash
alembic upgrade head
alembic downgrade -1
alembic revision --autogenerate -m "add new table"
```

默认读取 `QUANT_DATABASE_URL`，未设置时使用 `sqlite:///./var/quant.db`。
