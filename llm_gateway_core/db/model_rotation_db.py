import sqlite3
import os
import logging
from pathlib import Path

class ModelRotationDB:
    def __init__(self, db_filename: str = "llmgateway_rotation.db"):
        """
        Initialize the database for tracking model rotation.

        Args:
            db_filename: The name of the SQLite database file.
                         It will be created in a 'db' directory at the project root.
        """
        # Determine project root (assuming this file is in llm_gateway_core/db)
        project_root = Path(__file__).parent.parent.parent
        db_dir = project_root / "db" # Place DB in a root-level 'db' directory
        db_path = db_dir / db_filename

        # Ensure the directory exists
        os.makedirs(db_dir, exist_ok=True)

        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """
        Initialize the database schema if it doesn't exist.
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

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
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get the current index
            cursor.execute(
                "SELECT last_model_index FROM model_rotation WHERE api_key = ? AND gateway_model = ?",
                (api_key, gateway_model)
            )
            result = cursor.fetchone()

            if result is None:
                # First time this API key and model are used
                next_index = 0
                cursor.execute(
                    "INSERT INTO model_rotation (api_key, gateway_model, last_model_index) VALUES (?, ?, ?)",
                    (api_key, gateway_model, next_index)
                )
            else:
                current_index = result[0]
                # Calculate the next index with wraparound
                next_index = (current_index + 1) % total_models
                cursor.execute(
                    "UPDATE model_rotation SET last_model_index = ? WHERE api_key = ? AND gateway_model = ?",
                    (next_index, api_key, gateway_model)
                )

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
