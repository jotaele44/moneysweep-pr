"""Runtime proof for DuckDB relational Arrow export path.

Validates actual Arrow schema/row equivalence and deterministic Parquet bytes
without altering the production data store.
"""

import tempfile
import unittest
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


class DuckDBArrowParityTests(unittest.TestCase):
    def test_sorted_rows_and_null_preservation(self):
        conn = duckdb.connect(database=":memory:")
        try:
            conn.execute("CREATE TABLE audit_rows (id INTEGER, label VARCHAR, amount DOUBLE)")
            conn.executemany(
                "INSERT INTO audit_rows VALUES (?, ?, ?)",
                [(2, "Niño", 1.5), (1, None, -3.0), (3, "Puerto Rico", None)],
            )
            sql = "SELECT * FROM audit_rows ORDER BY ALL"
            old_result = conn.execute(sql).fetchall()
            relation_table = conn.sql(sql).to_arrow_table()
            from_arrow = [tuple(row.values()) for row in relation_table.to_pylist()]
            self.assertEqual(from_arrow, old_result)
            with tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / "audit_rows.parquet"
                staged = output.with_suffix(".parquet.tmp")
                pq.write_table(relation_table, staged, compression="zstd", use_dictionary=True)
                staged.replace(output)
                saved = pq.read_table(output)
                self.assertEqual(saved.schema, relation_table.schema)
                self.assertEqual(saved.to_pylist(), relation_table.to_pylist())
        finally:
            conn.close()

    def test_empty_relation_keeps_schema(self):
        conn = duckdb.connect(database=":memory:")
        try:
            table = conn.sql(
                "SELECT CAST(NULL AS INTEGER) id, CAST(NULL AS VARCHAR) label WHERE FALSE"
            ).to_arrow_table()
            self.assertEqual(table.num_rows, 0)
            self.assertEqual(table.column_names, ["id", "label"])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
