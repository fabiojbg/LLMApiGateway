import sqlite3
import os
import logging
from pathlib import Path

class ModelRotationDB:
    def __init__(
        self,
        db_filename: str = "llmgateway_rotation.db",
        database_timeout_seconds: float = 30.0,
    ):
        """
        Initialize the database for tracking model rotation.

        Args:
            db_filename: The name of the SQLite database file.
                         It will be created in a 'app_data/db' directory at the project root.
        """
        # Determine project root (assuming this file is in llm_gateway_core/db)
        project_root = Path(__file__).parent.parent.parent
        db_path = Path(db_filename)
        if db_path.is_absolute():
            db_dir = db_path.parent
        else:
            db_dir = project_root / "app_data" / "db"
            db_path = db_dir / db_filename

        # Ensure the directory exists
        os.makedirs(db_dir, exist_ok=True)

        self.db_path = db_path
        self._database_is_new = not db_path.exists()
        self.database_timeout_seconds = database_timeout_seconds
        self.busy_timeout_ms = max(1, int(database_timeout_seconds * 1000))
        self._init_db()
    def _init_db(self):
        """
        Initialize the database schema if it doesn't exist.
        """
        conn = None
        try:
            conn = sqlite3.connect(
                self.db_path, timeout=self.database_timeout_seconds
            )
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            if self._database_is_new:
                cursor.execute("PRAGMA journal_mode = WAL")

            # Create table for tracking the last used model index for each API key and gateway model
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS model_rotation (
                api_key TEXT,
                gateway_model TEXT,
                last_model_index INTEGER,
                PRIMARY KEY (api_key, gateway_model)
            )
            ''')

            conn.commit()
            logging.info(f"Model rotation database initialized at {self.db_path}")
        except Exception as e:
            logging.error(f"Error initializing model rotation database: {str(e)}")
            if conn:
                conn.rollback()
            raise # Re-raise the exception after logging
        finally:
            if conn:
                conn.close()

    def get_next_model_index(self, api_key: str, gateway_model: str, total_models: int) -> int:
        """
        Get the next model index to use for the given API key and gateway model.

        Args:
            api_key: The API key used in the request
            gateway_model: The gateway model name
            total_models: The total number of models in the fallback sequence

        Returns:
            The index of the next model to use (0-based).
        """
        if total_models <= 0:
            logging.warning("Cannot get next model index with zero or negative total models.")
            return 0 # Or raise an error?

        conn = None
        try:
            conn = sqlite3.connect(
                self.db_path, timeout=self.database_timeout_seconds
            )
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")

            cursor.execute(
                """
                INSERT INTO model_rotation (
                    api_key, gateway_model, last_model_index
                )
                VALUES (?, ?, 0)
                ON CONFLICT(api_key, gateway_model) DO UPDATE SET
                    last_model_index = (model_rotation.last_model_index + 1) % ?
                RETURNING last_model_index
                """,
                (api_key, gateway_model, total_models),
            )
            next_index = cursor.fetchone()[0]

            conn.commit()
            return next_index
        except Exception as e:
            logging.error(f"Error getting next model index for key='{api_key[:5]}...', model='{gateway_model}': {str(e)}")
            if conn:
                conn.rollback()
            # Default to first model in case of error to ensure graceful degradation
            return 0
        finally:
            if conn:
                conn.close()
