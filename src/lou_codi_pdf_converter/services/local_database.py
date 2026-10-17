from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from ..paths import application_data_directory

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StockSheet:
    id: int
    label: str
    material: str
    width_mm: float
    height_mm: float
    thickness_mm: float | None
    quantity: int
    status: str

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sheet_stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL DEFAULT '',
    material TEXT NOT NULL DEFAULT '',
    width_mm REAL NOT NULL CHECK(width_mm > 0),
    height_mm REAL NOT NULL CHECK(height_mm > 0),
    thickness_mm REAL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity >= 0),
    status TEXT NOT NULL DEFAULT 'available'
        CHECK(status IN ('available', 'reserved', 'used', 'scrap')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cutting_project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    blade_width_mm REAL NOT NULL DEFAULT 3 CHECK(blade_width_mm >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cutting_part (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES cutting_project(id) ON DELETE CASCADE,
    label TEXT NOT NULL DEFAULT '',
    width_mm REAL NOT NULL CHECK(width_mm > 0),
    height_mm REAL NOT NULL CHECK(height_mm > 0),
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
    rotation_allowed INTEGER NOT NULL DEFAULT 1 CHECK(rotation_allowed IN (0, 1))
);

CREATE TABLE IF NOT EXISTS stock_remnant (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_sheet_id INTEGER REFERENCES sheet_stock(id) ON DELETE SET NULL,
    material TEXT NOT NULL DEFAULT '',
    width_mm REAL NOT NULL CHECK(width_mm > 0),
    height_mm REAL NOT NULL CHECK(height_mm > 0),
    thickness_mm REAL,
    reusable INTEGER NOT NULL DEFAULT 1 CHECK(reusable IN (0, 1)),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cutting_part_project ON cutting_part(project_id);
CREATE INDEX IF NOT EXISTS idx_sheet_stock_status ON sheet_stock(status);
CREATE INDEX IF NOT EXISTS idx_stock_remnant_reusable ON stock_remnant(reusable);
"""


def database_path() -> Path:
    return application_data_directory() / "loucodi.db"


def initialize_database(path: Path | None = None) -> Path:
    """Create or migrate the local business database without any network access."""
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(target)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        row = connection.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
        if row is None:
            connection.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
        elif int(row[0]) > SCHEMA_VERSION:
            raise RuntimeError(
                "La base locale a été créée par une version plus récente de Lou Còdi."
            )
        connection.commit()
    return target


def add_stock_sheet(
    label: str,
    material: str,
    width_mm: float,
    height_mm: float,
    thickness_mm: float | None,
    quantity: int,
    *,
    path: Path | None = None,
) -> int:
    target = initialize_database(path)
    with closing(sqlite3.connect(target)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO sheet_stock(label, material, width_mm, height_mm, thickness_mm, quantity)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (label.strip(), material.strip(), width_mm, height_mm, thickness_mm, quantity),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_stock_sheets(*, path: Path | None = None, available_only: bool = False) -> list[StockSheet]:
    target = initialize_database(path)
    query = "SELECT id, label, material, width_mm, height_mm, thickness_mm, quantity, status FROM sheet_stock"
    parameters: tuple[object, ...] = ()
    if available_only:
        query += " WHERE status = ? AND quantity > 0"
        parameters = ("available",)
    query += " ORDER BY material, thickness_mm, width_mm * height_mm DESC, id"
    with closing(sqlite3.connect(target)) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [StockSheet(*row) for row in rows]


def set_stock_sheet_status(sheet_id: int, status: str, *, path: Path | None = None) -> None:
    if status not in {"available", "reserved", "used", "scrap"}:
        raise ValueError("État de plaque incorrect.")
    target = initialize_database(path)
    with closing(sqlite3.connect(target)) as connection:
        connection.execute(
            "UPDATE sheet_stock SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, sheet_id),
        )
        connection.commit()
