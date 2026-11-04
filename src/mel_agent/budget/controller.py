"""Application-level Bedrock spending control.

Policy values (cutoff, ceiling, estimate factors) are CONFIGURATION
(``MEL_BUDGET_*``), set for this hackathon to $225 / $250. They are not business
rules of survey generation or eligibility and can be changed without touching
either.

How it works
- Every paid call first RESERVES a conservative estimate in a durable ledger:
  input tokens from text length at ``budget_chars_per_token`` chars/token, output
  at the full ``max_tokens``, times the transport retry count, times
  ``budget_safety_factor``.
- A reservation is refused when committed + estimate would exceed the cutoff.
  Committed = settled actual costs + open reservations + unresolved attempts.
- After the call the reservation is SETTLED with verified usage. If usage cannot
  be established, or the outcome is unknown (timeout after the request left),
  the estimate stays committed as UNRESOLVED until a human RECONCILES it against
  the AWS bill (``reconcile``). Fail closed.
- Money is handled as fixed-precision Decimal (6 places). Every ledger row is
  validated on read: unknown kinds, negative or non-finite amounts, settlements
  without a reservation, or two final states for one reservation mean the ledger
  is corrupt and ALL reservations are refused until it is repaired.

Limitations (important)
- This meters only calls made through this application. Console use, other
  tools or accounts spend outside it and are invisible here.
- AWS billing lags by hours; the ledger is the real-time guard, the bill is the
  source of truth. Estimates err high on purpose. No absolute billing guarantee
  can be given by application code.
"""

from __future__ import annotations

import math
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterator

from mel_agent.config import Settings
from mel_agent.llm.pricing import BudgetState, PricingTable, TokenUsage, budget_state
from mel_agent.store import Store

MONEY = Decimal("0.000001")
_FINAL_KINDS = ("settle", "release", "unresolved")
_KINDS = ("reserve", "refused", "reconcile", *_FINAL_KINDS)


class BudgetError(RuntimeError):
    pass


class BudgetExceeded(BudgetError):
    """The reservation would push committed spend past the cutoff."""


class BudgetUnavailable(BudgetError):
    """Pricing or ledger state is unreliable; refusing (fail closed)."""


class PaidInferenceDisabled(BudgetError):
    """MEL_ALLOW_PAID_INFERENCE is not enabled."""


class InvalidTransition(BudgetError):
    """A reservation was settled/released twice, or finalised without being reserved."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def money(value: Any) -> Decimal:
    """Parse a monetary amount strictly: finite, non-negative, 6 decimal places."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise BudgetUnavailable("ledger contains a non-numeric amount") from None
    if not d.is_finite() or d < 0:
        raise BudgetUnavailable("ledger contains a negative or non-finite amount")
    return d.quantize(MONEY, rounding=ROUND_HALF_UP)


@dataclass
class Reservation:
    reservation_id: str
    model_id: str
    estimated_usd: Decimal
    created_at: str
    usage: TokenUsage | None = None
    outcome: str = "open"  # open | settled | released | unresolved


@dataclass
class BudgetStatus:
    cutoff_usd: float
    ceiling_usd: float
    settled_usd: float
    open_reserved_usd: float
    unresolved_usd: float
    committed_usd: float
    remaining_to_cutoff_usd: float
    state: str
    calls_settled: int
    calls_refused: int
    unresolved_count: int
    paid_inference_enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class BudgetController:
    def __init__(self, store: Store, settings: Settings, pricing: PricingTable | None) -> None:
        self.store = store
        self.settings = settings
        self.pricing = pricing
        self._lock = threading.RLock()
        self.cutoff = money(settings.budget_stop_usd)
        self.ceiling = money(settings.budget_max_usd)
        if self.cutoff > self.ceiling:
            raise BudgetUnavailable("budget cutoff above ceiling")

    # ---------- estimates ----------

    def estimate_tokens(self, text: str) -> int:
        return int(len(text) / self.settings.budget_chars_per_token) + 1

    def estimate_cost(self, model_id: str, input_tokens: int, max_output_tokens: int, attempts: int = 1) -> Decimal:
        if self.pricing is None:
            raise BudgetUnavailable("no pricing table loaded; refusing paid inference")
        price = self.pricing.price_for(model_id)
        if price is None:
            raise BudgetUnavailable("no pricing entry for the configured model; refusing paid inference")
        if input_tokens < 0 or max_output_tokens < 0 or attempts < 1:
            raise BudgetUnavailable("invalid token or attempt count for estimate")
        raw = price.cost(TokenUsage(input_tokens=input_tokens, output_tokens=max_output_tokens))
        if not math.isfinite(raw):
            raise BudgetUnavailable("non-finite cost estimate")
        return money(Decimal(str(raw)) * Decimal(attempts) * Decimal(str(self.settings.budget_safety_factor)))

    # ---------- ledger reads (validated) ----------

    def _ledger_rows(self, conn) -> list[dict[str, Any]]:
        # Insertion order matters (reserve before settle). created_at has microseconds; rowid breaks ties.
        return [dict(r) for r in conn.execute("SELECT reservation_id, kind, model_id, estimated_usd, actual_usd FROM budget_ledger ORDER BY created_at, rowid")]

    def _summarise(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        by_res: dict[str, dict[str, Any]] = {}
        refused = 0
        for r in rows:
            kind = r["kind"]
            if kind not in _KINDS:
                raise BudgetUnavailable("ledger contains an unknown entry kind")
            estimated = money(r["estimated_usd"])
            if kind == "refused":
                refused += 1
                continue
            entry = by_res.get(r["reservation_id"])
            if kind == "reserve":
                if entry is not None:
                    raise BudgetUnavailable("ledger reserves the same reservation twice")
                by_res[r["reservation_id"]] = {"estimated": estimated, "final": None, "actual": None, "reconciled": None}
                continue
            if entry is None:
                raise BudgetUnavailable("ledger finalises a reservation that was never reserved")
            if kind == "reconcile":
                if entry["final"] != "unresolved":
                    raise BudgetUnavailable("ledger reconciles a reservation that is not unresolved")
                if entry["reconciled"] is not None:
                    raise BudgetUnavailable("ledger reconciles the same reservation twice")
                if r["actual_usd"] is None:
                    raise BudgetUnavailable("ledger reconciliation without an amount")
                entry["reconciled"] = money(r["actual_usd"])
                continue
            if entry["final"] is not None:
                raise BudgetUnavailable("ledger has two final states for one reservation")
            entry["final"] = kind
            if kind == "settle":
                if r["actual_usd"] is None:
                    raise BudgetUnavailable("ledger has a settlement without an amount")
                entry["actual"] = money(r["actual_usd"])
        settled = open_ = unresolved = Decimal(0)
        calls_settled = unresolved_count = 0
        for e in by_res.values():
            if e["final"] == "settle":
                calls_settled += 1
                settled += e["actual"]
            elif e["final"] == "release":
                continue
            elif e["final"] == "unresolved":
                if e["reconciled"] is not None:
                    settled += e["reconciled"]
                    calls_settled += 1
                else:
                    unresolved += e["estimated"]
                    unresolved_count += 1
            else:
                open_ += e["estimated"]
        return {"settled": settled, "open": open_, "unresolved": unresolved, "committed": settled + open_ + unresolved,
                "calls_settled": calls_settled, "refused": refused, "unresolved_count": unresolved_count, "by_res": by_res}

    def status(self) -> BudgetStatus:
        with self.store.read() as conn:
            s = self._summarise(self._ledger_rows(conn))
        committed = s["committed"]
        return BudgetStatus(
            cutoff_usd=float(self.cutoff), ceiling_usd=float(self.ceiling), settled_usd=float(s["settled"]),
            open_reserved_usd=float(s["open"]), unresolved_usd=float(s["unresolved"]), committed_usd=float(committed),
            remaining_to_cutoff_usd=float(max(self.cutoff - committed, Decimal(0))),
            state=budget_state(float(committed), float(self.cutoff), float(self.ceiling)).value,
            calls_settled=s["calls_settled"], calls_refused=s["refused"], unresolved_count=s["unresolved_count"],
            paid_inference_enabled=self.settings.allow_paid_inference,
        )

    # ---------- lifecycle ----------

    def _insert(self, conn, reservation_id: str, kind: str, model_id: str, estimated: Decimal, actual: Decimal | None = None,
                usage: TokenUsage | None = None, note: str | None = None) -> None:
        # The (reservation_id, kind) unique index in the store is the storage-level guard against a second
        # settle/release/unresolved/reconcile row; a violation surfaces as InvalidTransition.
        try:
            self._insert_row(conn, reservation_id, kind, model_id, estimated, actual, usage, note)
        except sqlite3.IntegrityError as exc:
            raise InvalidTransition(f"duplicate ledger event '{kind}' for this reservation") from exc

    def _insert_row(self, conn, reservation_id: str, kind: str, model_id: str, estimated: Decimal, actual: Decimal | None,
                    usage: TokenUsage | None, note: str | None) -> None:
        conn.execute(
            "INSERT INTO budget_ledger (entry_id, reservation_id, created_at, kind, model_id, estimated_usd, actual_usd, input_tokens, output_tokens, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), reservation_id, _now(), kind, model_id, str(estimated), None if actual is None else str(actual),
             usage.input_tokens if usage else None, usage.output_tokens if usage else None, note))

    def reserve(self, model_id: str, input_tokens: int, max_output_tokens: int, attempts: int = 1) -> Reservation:
        """Atomically check headroom and record the reservation. Raises on refusal.

        The check and the insert run in one BEGIN IMMEDIATE transaction, so
        concurrent callers in other threads or processes serialise on the database."""
        if not self.settings.allow_paid_inference:
            raise PaidInferenceDisabled("paid inference is disabled (set MEL_ALLOW_PAID_INFERENCE=true to enable)")
        estimate = self.estimate_cost(model_id, input_tokens, max_output_tokens, attempts)
        with self._lock:
            refused_at: Decimal | None = None
            rid = str(uuid.uuid4())
            with self.store.write() as conn:
                summary = self._summarise(self._ledger_rows(conn))
                self._require_reconcilable(summary)
                committed = summary["committed"]
                if committed + estimate > self.cutoff:
                    refused_at = committed
                else:
                    self._insert(conn, rid, "reserve", model_id, estimate)
            if refused_at is not None:
                with self.store.write() as conn:  # own transaction, so the refusal survives the exception
                    self._insert(conn, str(uuid.uuid4()), "refused", model_id, estimate, note=f"committed={refused_at} cutoff={self.cutoff}")
                raise BudgetExceeded(
                    f"budget cutoff reached: committed ${refused_at} + estimate ${estimate} would exceed the "
                    f"${self.cutoff} automatic cutoff (ceiling ${self.ceiling})")
        return Reservation(rid, model_id, estimate, _now())

    def check_headroom(self, model_id: str, input_tokens: int, max_output_tokens: int, attempts: int = 1) -> Decimal:
        """Dry run of ``reserve``: raises exactly as reserve would, writes nothing, returns the estimate."""
        if not self.settings.allow_paid_inference:
            raise PaidInferenceDisabled("paid inference is disabled (set MEL_ALLOW_PAID_INFERENCE=true to enable)")
        estimate = self.estimate_cost(model_id, input_tokens, max_output_tokens, attempts)
        with self.store.read() as conn:
            summary = self._summarise(self._ledger_rows(conn))
        self._require_reconcilable(summary)
        committed = summary["committed"]
        if committed + estimate > self.cutoff:
            raise BudgetExceeded(f"budget cutoff reached: committed ${committed} + estimate ${estimate} would exceed the "
                                 f"${self.cutoff} automatic cutoff (ceiling ${self.ceiling})")
        return estimate

    def _require_reconcilable(self, summary: dict[str, Any]) -> None:
        """Spending uncertainty must stay reconcilable: refuse new paid attempts while too many are unresolved."""
        cap = int(getattr(self.settings, "budget_max_unresolved", 3))
        if summary["unresolved_count"] >= cap:
            raise BudgetUnavailable(f"{summary['unresolved_count']} reservations are unresolved (limit {cap}); reconcile them "
                                    "(`python -m mel_agent budget reconcile`) before any further paid inference")

    def _require_open(self, conn, reservation: Reservation) -> None:
        state = self._summarise(self._ledger_rows(conn))["by_res"].get(reservation.reservation_id)
        if state is None:
            raise InvalidTransition("reservation does not exist in the ledger")
        if state["final"] is not None:
            raise InvalidTransition(f"reservation already finalised ({state['final']})")

    def settle(self, reservation: Reservation, usage: TokenUsage | None) -> float:
        """Record actual cost (returned as float for display). Unknown usage => estimate stays committed (unresolved)."""
        with self._lock, self.store.write() as conn:
            self._require_open(conn, reservation)
            if usage is None:
                self._insert(conn, reservation.reservation_id, "unresolved", reservation.model_id, reservation.estimated_usd, note="no verified usage")
                reservation.outcome = "unresolved"
                return float(reservation.estimated_usd)
            price = self.pricing.price_for(reservation.model_id) if self.pricing else None
            if price is None:
                self._insert(conn, reservation.reservation_id, "unresolved", reservation.model_id, reservation.estimated_usd, note="pricing missing at settlement")
                reservation.outcome = "unresolved"
                return float(reservation.estimated_usd)
            actual = money(Decimal(str(price.cost(usage))))
            note = "actual exceeded estimate" if actual > reservation.estimated_usd else None
            self._insert(conn, reservation.reservation_id, "settle", reservation.model_id, reservation.estimated_usd, actual, usage, note)
            reservation.outcome, reservation.usage = "settled", usage
            return float(actual)

    def release(self, reservation: Reservation, reason: str) -> None:
        """Free a reservation for a request that certainly was not billed (rejected before inference)."""
        with self._lock, self.store.write() as conn:
            self._require_open(conn, reservation)
            self._insert(conn, reservation.reservation_id, "release", reservation.model_id, reservation.estimated_usd, Decimal(0), note=reason[:200])
            reservation.outcome = "released"

    def mark_unresolved(self, reservation: Reservation, reason: str) -> None:
        """The request may have been billed. Keep the estimate committed until reconciled."""
        with self._lock, self.store.write() as conn:
            self._require_open(conn, reservation)
            self._insert(conn, reservation.reservation_id, "unresolved", reservation.model_id, reservation.estimated_usd, note=reason[:200])
            reservation.outcome = "unresolved"

    @contextmanager
    def charge(self, model_id: str, input_text: str, max_output_tokens: int, attempts: int = 1) -> Iterator[Reservation]:
        """reserve -> yield -> settle(reservation.usage). Unknown usage or any exception leaves the estimate committed."""
        reservation = self.reserve(model_id, self.estimate_tokens(input_text), max_output_tokens, attempts)
        try:
            yield reservation
        except BaseException:
            if reservation.outcome == "open":
                self.mark_unresolved(reservation, "exception during paid call")
            raise
        else:
            if reservation.outcome == "open":
                self.settle(reservation, reservation.usage)

    def reconcile(self, reservation_id: str, actual_usd: Any, note: str) -> float:
        """Manual reconciliation of an unresolved reservation against the AWS bill."""
        amount = money(actual_usd)
        with self._lock, self.store.write() as conn:
            state = self._summarise(self._ledger_rows(conn))["by_res"].get(reservation_id)
            if state is None or state["final"] != "unresolved" or state["reconciled"] is not None:
                raise InvalidTransition("only an unreconciled, unresolved reservation can be reconciled")
            model_id = conn.execute("SELECT model_id FROM budget_ledger WHERE reservation_id = ? LIMIT 1", (reservation_id,)).fetchone()[0]
            self._insert(conn, reservation_id, "reconcile", model_id, state["estimated"], amount, note=note[:200])
        return float(amount)

    def unresolved(self) -> list[dict[str, Any]]:
        with self.store.read() as conn:
            s = self._summarise(self._ledger_rows(conn))
        return [{"reservation_id": rid, "estimated_usd": float(e["estimated"])} for rid, e in s["by_res"].items()
                if e["final"] == "unresolved" and e["reconciled"] is None]

    def ledger(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.store.read() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM budget_ledger ORDER BY created_at DESC, entry_id LIMIT ?", (min(limit, 1000),))]

    def state_is_ok(self) -> bool:
        return self.status().state == BudgetState.OK.value
