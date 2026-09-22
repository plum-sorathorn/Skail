from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from skail.domain.usage import NormalizedUsage, UsageAuthority
from skail.sessions.journal import Journal, JournalIdempotencyError, JournalTransaction, _now


class BudgetBlockedError(RuntimeError):
    code = "budget.blocked"


class ReservationStateError(RuntimeError):
    pass


class ReservationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    reservation_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task_id: str | None
    amount_usd: Decimal = Field(ge=0)
    idempotency_key: str = Field(min_length=1)
    purpose: str = "task_attempt"


class ReservationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    reservation_id: str
    amount_usd: Decimal
    warning_crossed: bool = False


class BudgetSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    hard_limit_usd: Decimal | None
    authoritative_actual_usd: Decimal
    estimated_actual_usd: Decimal
    reserved_usd: Decimal
    available_usd: Decimal | None


def _decimal_sum(rows: list[sqlite3.Row]) -> Decimal:
    return sum((Decimal(row[0]) for row in rows), Decimal("0"))


class BudgetLedger:
    def __init__(self, journal: Journal, *, warning_percent: Decimal = Decimal("0.80")) -> None:
        if not Decimal("0") < warning_percent <= Decimal("1"):
            raise ValueError("warning_percent must be above zero and at most one")
        self.journal = journal
        self.warning_percent = warning_percent

    def snapshot(self, run_id: str) -> BudgetSnapshot:
        with self.journal._connect() as connection:
            return self._snapshot(connection, run_id)

    def _snapshot(self, connection: sqlite3.Connection, run_id: str) -> BudgetSnapshot:
        run = connection.execute(
            "SELECT budget_limit_usd FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if run is None:
            raise KeyError(run_id)
        usage = connection.execute(
            "SELECT amount_usd,authoritative FROM usage_records WHERE run_id=?", (run_id,)
        ).fetchall()
        actual = sum(
            (Decimal(row["amount_usd"]) for row in usage if row["authoritative"]),
            Decimal("0"),
        )
        estimated = sum(
            (Decimal(row["amount_usd"]) for row in usage if not row["authoritative"]),
            Decimal("0"),
        )
        reserved = _decimal_sum(
            connection.execute(
                "SELECT amount_usd FROM budget_reservations WHERE run_id=? AND status='reserved'",
                (run_id,),
            ).fetchall()
        )
        limit = None if run["budget_limit_usd"] is None else Decimal(run["budget_limit_usd"])
        return BudgetSnapshot(
            hard_limit_usd=limit,
            authoritative_actual_usd=actual,
            estimated_actual_usd=estimated,
            reserved_usd=reserved,
            available_usd=None if limit is None else limit - actual - estimated - reserved,
        )

    @staticmethod
    def task_committed_usd(
        connection: sqlite3.Connection, run_id: str, task_id: str
    ) -> Decimal:
        usage = _decimal_sum(
            connection.execute(
                "SELECT amount_usd FROM usage_records WHERE run_id=? AND task_id=?",
                (run_id, task_id),
            ).fetchall()
        )
        reserved = _decimal_sum(
            connection.execute(
                "SELECT amount_usd FROM budget_reservations "
                "WHERE run_id=? AND task_id=? AND status='reserved'",
                (run_id, task_id),
            ).fetchall()
        )
        return usage + reserved

    def reserve(
        self,
        request: ReservationRequest,
        *,
        task_limit_usd: Decimal | None = None,
        lead_allowance_usd: Decimal = Decimal("0"),
    ) -> ReservationResult:
        with self.journal.transaction() as transaction:
            return self.reserve_in_transaction(
                transaction,
                request,
                task_limit_usd=task_limit_usd,
                lead_allowance_usd=lead_allowance_usd,
            )

    def reserve_in_transaction(
        self,
        transaction: JournalTransaction,
        request: ReservationRequest,
        *,
        task_limit_usd: Decimal | None = None,
        lead_allowance_usd: Decimal = Decimal("0"),
    ) -> ReservationResult:
        connection = transaction.connection
        replay = connection.execute(
            "SELECT reservation_id,run_id,task_id,amount_usd,idempotency_key,purpose "
            "FROM budget_reservations WHERE idempotency_key=?",
            (request.idempotency_key,),
        ).fetchone()
        if replay is not None:
            expected = (
                request.reservation_id,
                request.run_id,
                request.task_id,
                format(request.amount_usd, "f"),
                request.idempotency_key,
                request.purpose,
            )
            if tuple(replay) != expected:
                raise JournalIdempotencyError(
                    "session.idempotency_conflict",
                    "reservation replay conflicts",
                    idempotency_key=request.idempotency_key,
                )
            return ReservationResult(
                reservation_id=request.reservation_id, amount_usd=request.amount_usd
            )
        snapshot = self._snapshot(connection, request.run_id)
        if snapshot.available_usd is not None and (
            request.amount_usd + lead_allowance_usd > snapshot.available_usd
        ):
            raise BudgetBlockedError("run budget cannot fund reservation and lead allowance")
        if task_limit_usd is not None and request.task_id is not None:
            task_usage = _decimal_sum(
                connection.execute(
                    "SELECT amount_usd FROM usage_records WHERE run_id=? AND task_id=?",
                    (request.run_id, request.task_id),
                ).fetchall()
            )
            task_reserved = _decimal_sum(
                connection.execute(
                    "SELECT amount_usd FROM budget_reservations "
                    "WHERE run_id=? AND task_id=? AND status='reserved'",
                    (request.run_id, request.task_id),
                ).fetchall()
            )
            if task_usage + task_reserved + request.amount_usd > task_limit_usd:
                raise BudgetBlockedError("task budget cannot fund reservation")
        transaction.create_reservation(
            reservation_id=request.reservation_id,
            run_id=request.run_id,
            task_id=request.task_id,
            amount_usd=request.amount_usd,
            status="reserved",
            idempotency_key=request.idempotency_key,
            created_at=datetime.now(UTC),
            purpose=request.purpose,
        )
        warning = self._update_warning(connection, request.run_id)
        return ReservationResult(
            reservation_id=request.reservation_id,
            amount_usd=request.amount_usd,
            warning_crossed=warning,
        )

    def release(self, reservation_id: str) -> None:
        with self.journal.transaction() as transaction:
            row = transaction.connection.execute(
                "SELECT run_id,status FROM budget_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(reservation_id)
            if row["status"] == "released":
                return
            if row["status"] != "reserved":
                raise ReservationStateError(f"cannot release {row['status']} reservation")
            transaction.connection.execute(
                "UPDATE budget_reservations SET status='released',updated_at=? "
                "WHERE reservation_id=?",
                (_now(), reservation_id),
            )
            self._update_warning(transaction.connection, row["run_id"])

    def settle(
        self,
        reservation_id: str,
        *,
        usage_id: str,
        usage: NormalizedUsage,
        idempotency_key: str,
    ) -> None:
        with self.journal.transaction() as transaction:
            connection = transaction.connection
            reservation = connection.execute(
                "SELECT run_id,task_id,status FROM budget_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if reservation is None:
                raise KeyError(reservation_id)
            existing = connection.execute(
                "SELECT usage_id,amount_usd,authoritative,idempotency_key "
                "FROM usage_records WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            authoritative = usage.authority is UsageAuthority.AUTHORITATIVE_ACTUAL
            values = (usage_id, format(usage.cost_usd, "f"), int(authoritative), idempotency_key)
            if existing is not None:
                if tuple(existing) == values:
                    return
                if (
                    not existing["authoritative"]
                    and authoritative
                    and (
                        existing["usage_id"] == usage_id
                        and existing["idempotency_key"] == idempotency_key
                    )
                ):
                    connection.execute(
                        "UPDATE usage_records SET amount_usd=?,authoritative=1 "
                        "WHERE reservation_id=?",
                        (format(usage.cost_usd, "f"), reservation_id),
                    )
                    self._update_warning(connection, reservation["run_id"])
                    return
                raise JournalIdempotencyError(
                    "session.idempotency_conflict",
                    "usage replay conflicts",
                    idempotency_key=idempotency_key,
                )
            if reservation["status"] != "reserved":
                raise ReservationStateError(f"cannot settle {reservation['status']} reservation")
            connection.execute(
                "INSERT INTO usage_records "
                "(usage_id,run_id,task_id,amount_usd,authoritative,idempotency_key,"
                "created_at,reservation_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    usage_id,
                    reservation["run_id"],
                    reservation["task_id"],
                    format(usage.cost_usd, "f"),
                    int(authoritative),
                    idempotency_key,
                    _now(),
                    reservation_id,
                ),
            )
            connection.execute(
                "UPDATE budget_reservations SET status='settled',updated_at=? "
                "WHERE reservation_id=?",
                (_now(), reservation_id),
            )
            self._update_warning(connection, reservation["run_id"])

    def _update_warning(self, connection: sqlite3.Connection, run_id: str) -> bool:
        snapshot = self._snapshot(connection, run_id)
        above = bool(
            snapshot.hard_limit_usd is not None
            and snapshot.hard_limit_usd > 0
            and snapshot.hard_limit_usd - (snapshot.available_usd or Decimal("0"))
            >= snapshot.hard_limit_usd * self.warning_percent
        )
        prior = connection.execute(
            "SELECT is_above_threshold FROM budget_warning_state WHERE run_id=?", (run_id,)
        ).fetchone()
        was_above = bool(prior[0]) if prior is not None else False
        connection.execute(
            "INSERT INTO budget_warning_state VALUES (?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET warning_percent=excluded.warning_percent,"
            "is_above_threshold=excluded.is_above_threshold",
            (run_id, format(self.warning_percent, "f"), int(above)),
        )
        return above and not was_above
