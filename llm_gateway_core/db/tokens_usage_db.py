import sqlite3
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta

class TokensUsageDB:
    def __init__(self, db_filename: str = "tokens_usage.db"):
        """
        Initialize the database for tracking token usage.

        Args:
            db_filename: The name of the SQLite database file.
                         It will be created in a 'db' directory at the project root.
        """
        # Determine project root (assuming this file is in llm_gateway_core/db)
        project_root = Path(__file__).parent.parent.parent
        db_dir = project_root / "db"  # Place DB in a root-level 'db' directory
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

            # Create table for tracking token usage
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS tokens_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                reasoning_tokens INTEGER DEFAULT 0,
                cached_tokens INTEGER DEFAULT 0,
                cost REAL DEFAULT 0.0,
                model TEXT,
                provider TEXT
            )
            ''')

            # Create index on timestamp for efficient cleanup
            cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_tokens_usage_timestamp 
            ON tokens_usage (timestamp)
            ''')

            conn.commit()
            logging.info(f"Tokens usage database initialized at {self.db_path}")
        except Exception as e:
            logging.error(f"Error initializing tokens usage database: {str(e)}")
            if conn:
                conn.rollback()
            raise  # Re-raise the exception after logging
        finally:
            if conn:
                conn.close()

    def get_latest_usage_records(self, limit: int = 25, offset: int = 0):
        """
        Retrieve the latest token usage records with pagination.

        Args:
            limit (int): The maximum number of records to return. Defaults to 25.
            offset (int): The number of records to skip. Defaults to 0.

        Returns:
            list[dict]: A list of dictionaries, each representing a token usage record.
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            query = f"""
            SELECT
                id,
                timestamp,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                reasoning_tokens,
                cached_tokens,
                cost,
                model,
                provider
            FROM
                tokens_usage
            ORDER BY
                timestamp DESC
            LIMIT ? OFFSET ?
            """
            cursor.execute(query, (limit, offset))
            
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            results = [dict(zip(columns, row)) for row in rows]
            
            logging.debug(f"Retrieved {len(results)} latest token usage records (limit={limit}, offset={offset}).")
            return results

        except Exception as e:
            logging.error(f"Error retrieving latest token usage records: {str(e)}")
            return []
        finally:
            if conn:
                conn.close()

    def insert_usage(self, tokens_usage: dict):
        """
        Insert token usage data into the database.

        Args:
            tokens_usage: Dictionary containing token usage data with keys:
                - prompt_tokens, completion_tokens, total_tokens
                - reasoning_tokens, cached_tokens, cost
                - model, provider (optional)
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Prepare data for insertion
            timestamp = datetime.now().isoformat()
            prompt_tokens = tokens_usage.get('prompt_tokens', 0)
            completion_tokens = tokens_usage.get('completion_tokens', 0)
            total_tokens = tokens_usage.get('total_tokens', 0)
            reasoning_tokens = tokens_usage.get('reasoning_tokens', 0)
            cached_tokens = tokens_usage.get('cached_tokens', 0)
            cost = tokens_usage.get('cost', 0.0)
            model = tokens_usage.get('model')
            provider = tokens_usage.get('provider')

            cursor.execute('''
            INSERT INTO tokens_usage 
            (timestamp, prompt_tokens, completion_tokens, total_tokens, 
             reasoning_tokens, cached_tokens, cost, model, provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (timestamp, prompt_tokens, completion_tokens, total_tokens,
                  reasoning_tokens, cached_tokens, cost, model, provider))

            conn.commit()
            logging.debug(f"Inserted token usage data into database: {tokens_usage}")
        except Exception as e:
            logging.error(f"Error inserting token usage data: {str(e)}")
            if conn:
                conn.rollback()
            # Don't raise the exception to avoid breaking the logging functionality
        finally:
            if conn:
                conn.close()

    def cleanup_old_records(self, retention_days: int = 180):
        """
        Remove records older than the specified retention period.

        Args:
            retention_days: Number of days to keep records (default 180 for 6 months)
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Calculate cutoff date
            cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()

            cursor.execute('''
            DELETE FROM tokens_usage 
            WHERE timestamp < ?
            ''', (cutoff_date,))

            deleted_count = cursor.rowcount
            conn.commit()
            
            if deleted_count > 0:
                logging.info(f"Cleaned up {deleted_count} old token usage records (older than {retention_days} days)")
            else:
                logging.debug("No old token usage records to clean up")
                
        except Exception as e:
            logging.error(f"Error cleaning up old token usage records: {str(e)}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def get_total_records_count(self):
        """
        Retrieve the total number of records in the tokens_usage table.

        Returns:
            int: The total count of records.
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tokens_usage")
            count = cursor.fetchone()[0]
            logging.debug(f"Total number of token usage records: {count}")
            return count
        except Exception as e:
            logging.error(f"Error retrieving total token usage records count: {str(e)}")
            return 0
        finally:
            if conn:
                conn.close()

    def get_aggregated_usage(self, period: str, start_date: datetime = None, end_date: datetime = None):
        """
        Retrieve aggregated token usage data by specified period (hour, day, week, month) and model,
        optionally filtered by a date range.

        Args:
            period (str): The aggregation period ('hour', 'day', 'week', 'month').
            start_date (datetime, optional): The start of the date range to filter records. Defaults to None.
            end_date (datetime, optional): The end of the date range to filter records. Defaults to None.

        Returns:
            list[dict]: A list of dictionaries, each containing the aggregated usage
                        for a specific period and model.
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Determine the date formatting string based on the period
            if period == 'hour':
                date_format = '%Y-%m-%d %H:00:00'
            elif period == 'day':
                date_format = '%Y-%m-%d'
            elif period == 'week':
                # %W for week number (00-53) with Monday as the first day of the week
                date_format = '%Y-W%W'
            elif period == 'month':
                date_format = '%Y-%m'
            else:
                raise ValueError(f"Invalid period: {period}. Must be 'hour', 'day', 'week', or 'month'.")

            # Build the WHERE clause for date filtering
            where_clause = ""
            params = []
            if start_date:
                where_clause += " WHERE timestamp >= ?"
                params.append(start_date.isoformat())
            if end_date:
                if where_clause:
                    where_clause += " AND"
                else:
                    where_clause += " WHERE"
                where_clause += " timestamp <= ?"
                params.append(end_date.isoformat())

            query = f"""
            SELECT
                strftime('{date_format}', timestamp) as time_period,
                model,
                SUM(prompt_tokens) as prompt_tokens,
                SUM(completion_tokens) as completion_tokens,
                SUM(total_tokens) as total_tokens,
                SUM(reasoning_tokens) as reasoning_tokens,
                SUM(cached_tokens) as cached_tokens,
                SUM(cost) as cost
            FROM
                tokens_usage
            {where_clause}
            GROUP BY
                time_period, model
            ORDER BY
                time_period DESC, model ASC
            """
            cursor.execute(query, params)
            
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            results = [dict(zip(columns, row)) for row in rows]
            
            logging.debug(f"Retrieved aggregated token usage for period '{period}'. Records found: {len(results)}")
            return results

        except ValueError as ve:
            logging.error(f"Invalid period specified for tokens usage aggregation: {ve}")
            return []
        except Exception as e:
            logging.error(f"Error retrieving aggregated token usage for period '{period}': {str(e)}")
            return []
        finally:
            if conn:
                conn.close()
