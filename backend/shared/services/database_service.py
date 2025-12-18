import json
import logging
import os
from typing import List, Dict, Optional
from datetime import datetime
import asyncpg
from asyncpg.pool import Pool

logger = logging.getLogger(__name__)


class Database:
    """Database service for handling transcript storage using asyncpg"""

    _pool: Optional[Pool] = None

    @classmethod
    async def get_pool(cls) -> Pool:
        """Get or create database connection pool"""
        if cls._pool is None:
            database_url = os.getenv('DATABASE_URL')
            if not database_url:
                raise ValueError("DATABASE_URL environment variable is not set")

            try:
                cls._pool = await asyncpg.create_pool(
                    database_url,
                    min_size=1,
                    max_size=3,
                    command_timeout=10
                )
                logger.info("Database connection pool created successfully")
            except Exception as e:
                logger.error(f"Failed to create database pool: {e}")
                raise

        return cls._pool

    @classmethod
    async def save_transcript(cls, correlation_token: str, transcript_data: List[Dict]) -> bool:
        """Save transcript to simulation_attempts or interview_simulation_attempts table"""
        try:
            pool = await cls.get_pool()

            # Prepare transcript JSON
            transcript_json = {
                "messages": transcript_data,
                "capturedAt": datetime.utcnow().isoformat(),
                "version": "1.0"
            }

            # Determine which table contains the session and update only that table
            async with pool.acquire() as connection:
                table_name = await connection.fetchval(
                    """
                    SELECT 'simulation_attempts'::text
                    FROM simulation_attempts
                    WHERE "correlationToken" = $1
                    UNION ALL
                    SELECT 'interview_simulation_attempts'::text
                    FROM interview_simulation_attempts
                    WHERE "correlationToken" = $1
                    LIMIT 1
                    """,
                    correlation_token
                )

                if not table_name:
                    logger.warning(f"No simulation_attempts or interview_simulation_attempts record found for correlationToken: {correlation_token}")
                    return False

                # Update the appropriate table
                if table_name == 'simulation_attempts':
                    result = await connection.execute(
                        """
                        UPDATE simulation_attempts
                        SET transcript = $1::jsonb
                        WHERE "correlationToken" = $2
                        """,
                        json.dumps(transcript_json),
                        correlation_token
                    )
                elif table_name == 'interview_simulation_attempts':
                    result = await connection.execute(
                        """
                        UPDATE interview_simulation_attempts
                        SET transcript = $1::jsonb
                        WHERE "correlationToken" = $2
                        """,
                        json.dumps(transcript_json),
                        correlation_token
                    )
                else:
                    logger.error(f"Unexpected table name: {table_name}")
                    return False

                # Check if any rows were updated
                rows_affected = int(result.split()[-1]) if result else 0

                if rows_affected > 0:
                    logger.info(f"Transcript saved for {correlation_token} in {table_name}: {len(transcript_data)} messages")
                    return True
                else:
                    logger.warning(f"Failed to update transcript for correlationToken: {correlation_token} in {table_name}")
                    return False

        except asyncpg.exceptions.UndefinedTableError as e:
            logger.error(f"Table does not exist: {e}")
            return False
        except Exception as e:
            logger.error(f"Error saving transcript: {e}", exc_info=True)
            return False

    @classmethod
    async def close(cls):
        """Close database connection pool"""
        if cls._pool:
            try:
                await cls._pool.close()
                cls._pool = None
                logger.info("Database connection pool closed")
            except Exception as e:
                logger.error(f"Error closing database pool: {e}", exc_info=True)
