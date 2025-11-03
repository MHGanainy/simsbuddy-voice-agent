import os
import logging
from typing import Optional, Dict, Any
from enum import Enum
import asyncpg
from asyncpg.pool import Pool
import redis

logger = logging.getLogger(__name__)


class CreditDeductionResult(Enum):
    """Result of credit deduction operation"""
    SUCCESS = "success"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    ALREADY_BILLED = "already_billed"
    SESSION_NOT_FOUND = "session_not_found"
    STUDENT_NOT_FOUND = "student_not_found"
    ERROR = "error"


class CreditService:
    """
    Credit billing service for voice conversations.

    Handles per-minute billing with idempotency, database transactions,
    and Redis-based duplicate prevention.
    """

    _pool: Optional[Pool] = None
    _redis_client: Optional[redis.Redis] = None

    @classmethod
    async def get_pool(cls) -> Pool:
        """Get or create database connection pool (shared with Database service)"""
        if cls._pool is None:
            database_url = os.getenv('DATABASE_URL')
            if not database_url:
                raise ValueError("DATABASE_URL environment variable is not set")

            if database_url.startswith('prisma://'):
                logger.warning("Detected Prisma proxy URL, ensure you're using the direct PostgreSQL URL")

            try:
                cls._pool = await asyncpg.create_pool(
                    database_url,
                    min_size=1,
                    max_size=5,
                    command_timeout=10
                )
                logger.info("Credit service database connection pool created successfully")
            except Exception as e:
                logger.error(f"Failed to create database pool: {e}")
                raise

        return cls._pool

    @classmethod
    def get_redis_client(cls) -> redis.Redis:
        """Get or create Redis client"""
        if cls._redis_client is None:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            cls._redis_client = redis.from_url(redis_url, decode_responses=True)
            try:
                cls._redis_client.ping()
                logger.info("Credit service Redis connection established")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise

        return cls._redis_client

    @classmethod
    async def get_student_id_from_session(cls, session_id: str) -> Optional[str]:
        """
        Get student_id from SimulationAttempt using correlation_token.

        Args:
            session_id: The session ID (correlation_token)

        Returns:
            Student ID if found, None otherwise
        """
        try:
            pool = await cls.get_pool()

            async with pool.acquire() as connection:
                student_id = await connection.fetchval(
                    """
                    SELECT student_id
                    FROM simulation_attempts
                    WHERE "correlationToken" = $1
                    """,
                    session_id
                )

                if student_id:
                    logger.debug(f"Found student_id {student_id} for session {session_id}")
                else:
                    logger.warning(f"No SimulationAttempt found for session {session_id}")

                return student_id

        except Exception as e:
            logger.error(f"Error fetching student_id for session {session_id}: {e}", exc_info=True)
            return None

    @classmethod
    async def check_sufficient_credits(cls, student_id: str, required_credits: int) -> bool:
        """
        Check if student has sufficient credits.

        Args:
            student_id: The student's ID
            required_credits: Number of credits required

        Returns:
            True if student has sufficient credits, False otherwise
        """
        try:
            pool = await cls.get_pool()

            async with pool.acquire() as connection:
                credit_balance = await connection.fetchval(
                    """
                    SELECT credit_balance
                    FROM students
                    WHERE id = $1
                    """,
                    student_id
                )

                if credit_balance is None:
                    logger.warning(f"Student {student_id} not found")
                    return False

                has_sufficient = credit_balance >= required_credits
                logger.debug(f"Student {student_id} has {credit_balance} credits, needs {required_credits}: {has_sufficient}")
                return has_sufficient

        except Exception as e:
            logger.error(f"Error checking credits for student {student_id}: {e}", exc_info=True)
            return False

    @classmethod
    async def deduct_minute(cls, session_id: str, minute_number: int) -> Dict[str, Any]:
        """
        Deduct 1 credit for a specific minute of conversation.

        Uses Redis idempotency key to prevent double-charging.
        Creates audit trail in CreditTransaction table.
        Updates SimulationAttempt.minutesBilled.

        Args:
            session_id: The session ID (correlation_token)
            minute_number: The minute number being billed (1-indexed)

        Returns:
            Dict with:
                - result: CreditDeductionResult enum value
                - message: Human-readable message
                - student_id: Student ID (if found)
                - balance_after: Remaining balance (if deducted)
        """
        redis_client = cls.get_redis_client()
        idempotency_key = f"credit:billed:{session_id}:{minute_number}"

        # Check idempotency - already billed?
        if redis_client.exists(idempotency_key):
            logger.info(f"Minute {minute_number} for session {session_id} already billed (idempotent)")
            return {
                "result": CreditDeductionResult.ALREADY_BILLED,
                "message": f"Minute {minute_number} already billed",
                "session_id": session_id,
                "minute_number": minute_number
            }

        # Get student_id
        student_id = await cls.get_student_id_from_session(session_id)
        if not student_id:
            logger.error(f"Cannot bill session {session_id}: SimulationAttempt not found")
            return {
                "result": CreditDeductionResult.SESSION_NOT_FOUND,
                "message": "Session not found in database",
                "session_id": session_id
            }

        try:
            pool = await cls.get_pool()

            async with pool.acquire() as connection:
                async with connection.transaction():
                    # Lock and fetch student balance
                    student_row = await connection.fetchrow(
                        """
                        SELECT credit_balance
                        FROM students
                        WHERE id = $1
                        FOR UPDATE
                        """,
                        student_id
                    )

                    if not student_row:
                        logger.error(f"Student {student_id} not found")
                        return {
                            "result": CreditDeductionResult.STUDENT_NOT_FOUND,
                            "message": "Student not found",
                            "student_id": student_id
                        }

                    current_balance = student_row['credit_balance']

                    # Check sufficient credits
                    if current_balance < 1:
                        logger.warning(
                            f"Insufficient credits for student {student_id}: "
                            f"balance={current_balance}, required=1"
                        )
                        return {
                            "result": CreditDeductionResult.INSUFFICIENT_CREDITS,
                            "message": "Insufficient credits",
                            "student_id": student_id,
                            "balance": current_balance
                        }

                    # Deduct 1 credit
                    new_balance = current_balance - 1
                    await connection.execute(
                        """
                        UPDATE students
                        SET credit_balance = $1
                        WHERE id = $2
                        """,
                        new_balance,
                        student_id
                    )

                    # Create CreditTransaction audit record
                    await connection.execute(
                        """
                        INSERT INTO credit_transactions (
                            id,
                            student_id,
                            transaction_type,
                            amount,
                            balance_after,
                            source_type,
                            source_id,
                            description,
                            created_at
                        )
                        VALUES (
                            gen_random_uuid(),
                            $1,
                            'DEBIT',
                            1,
                            $2,
                            'SIMULATION',
                            $3,
                            $4,
                            NOW()
                        )
                        """,
                        student_id,
                        new_balance,
                        session_id,
                        f"Voice simulation - minute {minute_number}"
                    )

                    # Update SimulationAttempt.minutesBilled
                    await connection.execute(
                        """
                        UPDATE simulation_attempts
                        SET minutes_billed = $1
                        WHERE "correlationToken" = $2
                        """,
                        minute_number,
                        session_id
                    )

                    logger.info(
                        f"Credit deducted: student={student_id}, session={session_id}, "
                        f"minute={minute_number}, balance: {current_balance} -> {new_balance}"
                    )

            # Transaction succeeded - set idempotency key with 7-day TTL
            redis_client.setex(idempotency_key, 7 * 24 * 60 * 60, "1")

            return {
                "result": CreditDeductionResult.SUCCESS,
                "message": f"Successfully deducted 1 credit for minute {minute_number}",
                "student_id": student_id,
                "session_id": session_id,
                "minute_number": minute_number,
                "balance_after": new_balance
            }

        except Exception as e:
            logger.error(
                f"Error deducting credit for session {session_id}, minute {minute_number}: {e}",
                exc_info=True
            )
            return {
                "result": CreditDeductionResult.ERROR,
                "message": f"Database error: {str(e)}",
                "session_id": session_id,
                "error": str(e)
            }

    @classmethod
    async def reconcile_session(cls, session_id: str, total_minutes: int) -> Dict[str, Any]:
        """
        Reconcile billing at session end to ensure all minutes are billed.

        Bills any missing minutes from last billed minute to total minutes (rounded up).

        Args:
            session_id: The session ID (correlation_token)
            total_minutes: Total duration in minutes (should be rounded up)

        Returns:
            Dict with:
                - success: Boolean
                - message: Summary message
                - minutes_billed: Number of minutes billed in this reconciliation
                - total_billed: Total minutes billed after reconciliation
        """
        try:
            pool = await cls.get_pool()

            # Get current minutesBilled from SimulationAttempt
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    """
                    SELECT minutes_billed, student_id
                    FROM simulation_attempts
                    WHERE "correlationToken" = $1
                    """,
                    session_id
                )

                if not row:
                    logger.error(f"Cannot reconcile session {session_id}: not found")
                    return {
                        "success": False,
                        "message": "Session not found",
                        "session_id": session_id
                    }

                last_billed = row['minutes_billed'] or 0
                student_id = row['student_id']

            logger.info(
                f"Reconciling session {session_id}: last_billed={last_billed}, "
                f"total_minutes={total_minutes}"
            )

            # Bill any unbilled minutes
            minutes_billed_now = 0
            failed_minutes = []

            for minute in range(last_billed + 1, total_minutes + 1):
                result = await cls.deduct_minute(session_id, minute)

                if result['result'] in [CreditDeductionResult.SUCCESS, CreditDeductionResult.ALREADY_BILLED]:
                    minutes_billed_now += 1
                elif result['result'] == CreditDeductionResult.INSUFFICIENT_CREDITS:
                    logger.warning(
                        f"Insufficient credits during reconciliation: "
                        f"session={session_id}, minute={minute}"
                    )
                    failed_minutes.append(minute)
                    # Stop billing on insufficient credits
                    break
                else:
                    logger.error(f"Failed to bill minute {minute}: {result['message']}")
                    failed_minutes.append(minute)

            final_billed = last_billed + minutes_billed_now

            if failed_minutes:
                message = (
                    f"Reconciliation incomplete: billed {minutes_billed_now} minutes "
                    f"({last_billed} -> {final_billed}), failed minutes: {failed_minutes}"
                )
                logger.warning(message)
            else:
                message = (
                    f"Reconciliation complete: billed {minutes_billed_now} minutes "
                    f"({last_billed} -> {final_billed})"
                )
                logger.info(message)

            return {
                "success": len(failed_minutes) == 0,
                "message": message,
                "session_id": session_id,
                "student_id": student_id,
                "minutes_billed": minutes_billed_now,
                "total_billed": final_billed,
                "failed_minutes": failed_minutes
            }

        except Exception as e:
            logger.error(f"Error reconciling session {session_id}: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Error during reconciliation: {str(e)}",
                "session_id": session_id,
                "error": str(e)
            }

    @classmethod
    async def close(cls):
        """Close database connection pool and Redis client"""
        if cls._pool:
            try:
                await cls._pool.close()
                cls._pool = None
                logger.info("Credit service database connection pool closed")
            except Exception as e:
                logger.error(f"Error closing database pool: {e}", exc_info=True)

        if cls._redis_client:
            try:
                cls._redis_client.close()
                cls._redis_client = None
                logger.info("Credit service Redis connection closed")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}", exc_info=True)
