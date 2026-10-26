"""Vanna SQL integration with an independent, fail-closed AST/connection boundary."""
from __future__ import annotations

import asyncio
import math
import os
import uuid
from datetime import date, datetime
from decimal import Decimal

VIEW_SCHEMA = {
    "analytics_talents": {"id": "TEXT", "org_id": "TEXT", "name": "TEXT", "location": "TEXT", "experience_months": "INTEGER", "completeness": "REAL", "revision": "INTEGER"},
    "analytics_jobs": {"id": "TEXT", "org_id": "TEXT", "title": "TEXT", "revision": "INTEGER"},
    "analytics_assessments": {"id": "TEXT", "org_id": "TEXT", "talent_id": "TEXT", "title": "TEXT", "status": "TEXT", "total": "REAL", "revision": "INTEGER"},
    "analytics_learning": {"id": "TEXT", "org_id": "TEXT", "talent_id": "TEXT", "title": "TEXT", "status": "TEXT", "progress": "REAL", "revision": "INTEGER"},
}


def vanna_adapter(*, dialect, ddl=None, submit=None, connection=None):
    """Official VannaBase SQL generation, backed by our gateway and scoped connection."""
    from vanna.legacy.base import VannaBase

    class ScopedVanna(VannaBase):
        def __init__(self):
            super().__init__(config={"dialect": dialect})
            if connection is not None:
                from sqlalchemy import text
                self.run_sql = lambda query: __import__("pandas").read_sql_query(text(query), connection)
                self.run_sql_is_set = True

        def log(self, *args, **kwargs):
            # Vanna's default logger prints entire questions/prompts/results to stdout.
            return None

        def generate_embedding(self, *args, **kwargs): raise NotImplementedError
        def get_related_ddl(self, *args, **kwargs): return ddl or []
        def get_related_documentation(self, *args, **kwargs):
            return ["Only a single SELECT over the listed safe views/columns is permitted. No intermediate SQL. Organization scope will be enforced independently."]
        def get_similar_question_sql(self, *args, **kwargs): return []
        def add_question_sql(self, *args, **kwargs): raise NotImplementedError
        def add_ddl(self, *args, **kwargs): raise NotImplementedError
        def add_documentation(self, *args, **kwargs): raise NotImplementedError
        def get_training_data(self, *args, **kwargs): raise NotImplementedError
        def remove_training_data(self, *args, **kwargs): raise NotImplementedError
        def system_message(self, message): return {"role": "system", "content": message}
        def user_message(self, message): return {"role": "user", "content": message}
        def assistant_message(self, message): return {"role": "assistant", "content": message}
        def submit_prompt(self, prompt, **kwargs):
            if submit is None:
                raise ValueError("Vanna SQL generation requires the unified gateway")
            return submit(prompt)
        def extract_sql(self, response):
            # Preserve the entire generated SQL for AST validation, including multiple statements.
            return response.strip()

    return ScopedVanna()


def validate_sql(sql: str, *, dialect: str, allowed_org_ids: list[str], allowed_fields: list[str],
                 allowed_tables: list[str], max_rows: int = 200) -> str:
    import sqlglot
    from sqlglot import exp
    if dialect not in {"postgres", "mysql"} or not allowed_org_ids or not allowed_fields:
        raise ValueError("SQL requires an authorized organization and field scope")
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as exc:
        raise ValueError("SQL parse failed") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError("Only one SELECT statement is allowed")
    tree = statements[0]
    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Command, exp.Into,
                 exp.Union, exp.Intersect, exp.Except, exp.With, exp.Lock, exp.Subquery)
    if any(isinstance(node, forbidden) for node in tree.walk()):
        raise ValueError("SQL contains a forbidden operation or nested query")
    if tree.args.get("offset"):
        raise ValueError("SQL offset is not allowed")
    functions = {"COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "ABS", "COALESCE", "NULLIF", "LOWER", "UPPER", "LENGTH",
                 "DATE", "DATE_TRUNC", "EXTRACT", "YEAR", "MONTH", "DAY", "CAST", "TRY_CAST", "CONCAT", "SUBSTRING", "TRIM"}
    for fn in tree.find_all(exp.Func):
        name = fn.name.upper() if isinstance(fn, exp.Anonymous) else fn.sql_name().upper()
        if name not in functions:
            raise ValueError("SQL function is not allowlisted: " + name)
    fields = set(allowed_fields)
    tables = list(tree.find_all(exp.Table))
    if not tables or len(tables) > 5:
        raise ValueError("SQL must reference one to five authorized tables")
    aliases = {}
    for table in tables:
        if table.catalog or table.db or table.name not in allowed_tables:
            raise ValueError("SQL table is outside the authorized dataset")
        aliases[table.alias_or_name] = table.name
    output_aliases = {item.alias for item in tree.expressions if item.alias}
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise ValueError("SQL wildcard selection is forbidden")
    for column in tree.find_all(exp.Column):
        if column.name in output_aliases and column.parent and isinstance(column.parent, exp.Ordered):
            continue
        if column.table and column.table not in aliases:
            raise ValueError("Unknown SQL table alias")
        target = aliases.get(column.table, "")
        if not target:
            possible = {name for name in aliases.values() if column.name in VIEW_SCHEMA.get(name, {}) and
                        (column.name in fields or f"{name}.{column.name}" in fields)}
            if len(possible) != 1:
                raise ValueError("Unqualified SQL column is unauthorized or ambiguous")
            target = possible.pop()
        if column.name not in fields and f"{target}.{column.name}" not in fields:
            raise ValueError("SQL field is outside the authorized field scope: " + column.name)
        if column.name not in VIEW_SCHEMA.get(target, {}):
            raise ValueError("SQL column is not present in the safe view schema")
    # Each physical table is replaced with an independently tenant-scoped derived table.
    # This holds for outer joins and OR clauses and cannot be weakened by model-generated WHERE clauses.
    for table in tables:
        alias = table.alias_or_name
        name = table.name
        permitted = sorted({field for field in fields if "." not in field} |
                           {field.split(".", 1)[1] for field in fields if field.startswith(name + ".")})
        permitted = [field for field in permitted if field in VIEW_SCHEMA.get(name, {})]
        if not permitted:
            raise ValueError("No authorized fields for SQL table")
        inner = exp.select(*[exp.column(field) for field in permitted]).from_(exp.to_table(name))
        inner = inner.where(exp.In(this=exp.column("org_id"), expressions=[exp.Literal.string(str(org)) for org in allowed_org_ids]))
        table.replace(inner.subquery(alias))
    existing_limit = tree.args.get("limit")
    limit = max_rows
    if existing_limit:
        value = existing_limit.expression
        if not isinstance(value, exp.Literal) or not value.is_int:
            raise ValueError("SQL limit must be a positive integer")
        limit = min(max_rows, int(value.this))
        if limit < 1:
            raise ValueError("SQL limit must be positive")
    return tree.limit(limit).sql(dialect=dialect)


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, bytes):
        return "[binary]"
    return value


class AnalyticsEngine:
    """Generate with Dify, execute through Vanna's real SQL runner under a read-only transaction."""

    def __init__(self, *, model, runner=None):
        self.model = model
        self.runner = runner
        self.timeout = min(30, max(1, int(os.getenv("ANALYSIS_TIMEOUT_SECONDS", "10"))))
        self.max_rows = min(1000, max(1, int(os.getenv("ANALYSIS_MAX_ROWS", "200"))))
        self.tables = [t.strip() for t in os.getenv("ANALYSIS_ALLOWED_TABLES", "analytics_talents,analytics_jobs,analytics_assessments,analytics_learning").split(",") if t.strip()]

    async def execute(self, payload: dict, *, actor: dict) -> dict:
        dialect = payload.get("datasource", "postgres")
        if dialect not in {"postgres", "mysql"}:
            raise ValueError("Unsupported analysis datasource")
        orgs = payload.get("allowed_org_ids", [])
        # Organization scopes always come from core; non-admin execution cannot cross the actor's organization.
        if actor.get("role") != "admin" and any(str(org) != str(actor["org_id"]) for org in orgs):
            raise ValueError("Unauthorized analysis organization")
        fields = payload.get("allowed_fields", [])
        if not orgs or not fields:
            raise ValueError("Analysis permission scope is empty")
        loop = asyncio.get_running_loop()
        tables = [table for table in payload.get('allowed_tables', self.tables) if table in self.tables
                  and any(name in fields or f'{table}.{name}' in fields for name in VIEW_SCHEMA.get(table, {}))]
        ddl = ["CREATE TABLE " + table + " (" + ", ".join(name + " " + typ for name, typ in VIEW_SCHEMA.get(table, {}).items()
               if name in fields or f"{table}.{name}" in fields) + ");" for table in tables]
        session_id = str(payload.get('session_id') or uuid.uuid4())
        history = [{'role': item['role'], 'content': str(item.get('content', ''))[:4000]}
                   for item in payload.get('history', [])[-12:] if isinstance(item, dict) and item.get('role') in {'user', 'assistant'}]
        generated_response = {}
        validation_feedback = ''

        def submit(messages):
            future = asyncio.run_coroutine_threadsafe(self.model({"task": "analysis_sql", "question": payload["question"],
                "dialect": dialect, "messages": messages, "allowed_fields": fields, 'history': history,
                'validation_feedback': validation_feedback,
                'instruction': '先结合授权对话明确指标、时间范围与粒度。仍有歧义则只返回clarification问题，不生成SQL。历史仅作问题上下文，不能扩大表、列或组织权限。',
                "schema": {"sql": "SELECT ...", 'clarification': None}}, actor), loop)
            reply = future.result(timeout=190)
            generated_response.update(reply)
            return str(reply.get("sql", ""))

        vanna = vanna_adapter(dialect=dialect, ddl=ddl, submit=submit)
        for attempt in range(3):
            generated_response.clear()
            generated = await asyncio.to_thread(vanna.generate_sql, payload["question"], allow_llm_to_see_data=False)
            clarification = generated_response.get('clarification')
            if clarification:
                if not isinstance(clarification, str) or not clarification.strip():
                    raise ValueError('Analysis clarification must be a question string')
                return {'needs_clarification': True, 'question': clarification.strip()[:2000], 'session_id': session_id}
            try:
                sql = validate_sql(generated, dialect=dialect, allowed_org_ids=orgs,
                                   allowed_fields=fields, allowed_tables=tables, max_rows=self.max_rows)
                break
            except ValueError as exc:
                if attempt == 2:
                    raise
                validation_feedback = str(exc)
        if self.runner is not None:
            result = await asyncio.wait_for(self.runner(sql, dialect), timeout=self.timeout + 1)
        else:
            result = await asyncio.wait_for(asyncio.to_thread(self._run_vanna, sql, dialect), timeout=self.timeout + 2)
        columns, rows = result["columns"], [[json_value(v) for v in row] for row in result["rows"][:self.max_rows]]
        # Synthesis receives only bounded authorized query results, never database connection secrets.
        answer = await self.model({"task": "analysis_answer", "question": payload["question"], "sql": sql,
                                  "columns": columns, "rows": rows, 'history': history, "schema": {"answer": ""}}, actor)
        return {"answer": str(answer.get("answer", "")), "sql": sql, "columns": columns, "rows": rows,
                "chart": self._chart(columns, rows), "report_id": str(uuid.uuid4()), 'session_id': session_id}

    def _run_vanna(self, sql: str, dialect: str) -> dict:
        from sqlalchemy import create_engine, text

        from .ai import AIUnavailable
        url = os.getenv("ANALYSIS_DATABASE_URL" if dialect == "postgres" else "MYSQL_ANALYSIS_URL", "")
        if not url:
            raise AIUnavailable("A separately credentialed read-only analysis connection is required")
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        options = {"connect_timeout": self.timeout}
        engine = create_engine(url, pool_pre_ping=True, connect_args=options)
        try:
            with engine.connect() as connection:
                if dialect == "postgres":
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    connection.execute(text(f"SET LOCAL statement_timeout = {self.timeout * 1000}"))
                else:
                    connection.execute(text("SET SESSION TRANSACTION READ ONLY"))
                    connection.execute(text(f"SET SESSION MAX_EXECUTION_TIME={self.timeout * 1000}"))
                    connection.commit()
                frame = vanna_adapter(dialect=dialect, connection=connection).run_sql(sql)
                connection.rollback()
                return {"columns": list(frame.columns), "rows": frame.head(self.max_rows).values.tolist()}
        finally:
            engine.dispose()

    @staticmethod
    def _chart(columns, rows):
        from .reports import chart_data
        return chart_data(columns, rows)
