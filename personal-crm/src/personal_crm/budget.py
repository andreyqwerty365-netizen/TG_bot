from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .models import AIBudget, AIReservation, Profile, Source, SourceVersion


class AIError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def micro_usd(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            raise ValueError()
        return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
    except (ValueError, InvalidOperation):
        raise AIError("ai_configuration_invalid")


def price(config, now):
    try:
        item = json.loads(config.prices_json)[config.model]
        if item["currency"] != "USD" or not item["source"].startswith("https://"):
            raise ValueError()
        expiry = datetime.fromisoformat(item["valid_until"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= now:
            raise ValueError()
        input_rate, output_rate = Decimal(str(item["input_per_million"])), Decimal(str(item["output_per_million"]))
        ceiling = item["input_token_ceiling"]
        if (not input_rate.is_finite() or not output_rate.is_finite() or input_rate <= 0 or output_rate <= 0
            or type(ceiling) is not int or ceiling <= 0 or not 1 <= config.max_output_tokens <= 8192):
            raise ValueError()
        upper = int((ceiling * input_rate + config.max_output_tokens * output_rate).to_integral_value(rounding=ROUND_CEILING))
        return ceiling, input_rate, output_rate, upper
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise AIError("ai_configuration_invalid")


class BudgetLedger:
    def __init__(self, factory, clock):
        self.factory, self.clock = factory, clock

    def reserve(self, owner, source_id, model, limit, amount):
        period = self.clock().astimezone(UTC).date().replace(day=1)
        with self.factory.begin() as s:
            profile = s.scalar(select(Profile).where(Profile.id == owner).with_for_update())
            if not profile:
                raise AIError("ai_configuration_invalid")
            if profile.ai_paused:
                raise AIError("ai_disabled")
            if profile.ai_budget_cap_micro_usd is not None:
                limit = min(limit, profile.ai_budget_cap_micro_usd)
                if limit <= 0:
                    raise AIError("ai_budget_limit")
            if (type(limit) is not int or type(amount) is not int or limit <= 0 or amount <= 0 or
                not s.scalar(select(SourceVersion.id).join(Source).where(SourceVersion.id == source_id, Source.owner_id == owner))):
                raise AIError("ai_configuration_invalid")
            s.execute(insert(AIBudget).values(owner_id=owner, period=period, limit_micro_usd=limit).on_conflict_do_nothing())
            budget = s.scalar(select(AIBudget).where(AIBudget.owner_id == owner, AIBudget.period == period).with_for_update())
            # Lowered configuration takes effect immediately; increasing an existing month's limit
            # requires a deliberate new ledger setting, never a per-request bypass.
            budget.limit_micro_usd = min(budget.limit_micro_usd, limit)
            existing = s.scalar(select(AIReservation).where(AIReservation.source_version_id == source_id).with_for_update())
            if existing:
                if existing.owner_id != owner:
                    raise AIError("ai_previous_attempt")
                if existing.status == "settled" and existing.output and existing.model == model:
                    return existing.id, existing.output
                if existing.status != "failed" or existing.actual_micro_usd != 0:
                    raise AIError("ai_previous_attempt")
            total = budget.spent_micro_usd + budget.reserved_micro_usd
            if total + amount > budget.limit_micro_usd:
                raise AIError("ai_budget_limit")
            budget.reserved_micro_usd += amount
            budget.warning_80 = budget.warning_80 or (total + amount) * 100 >= budget.limit_micro_usd * 80
            # Only a provider rejection proven unbilled can reuse this source's slot.
            # The current month, model, limit and full amount are checked again under lock.
            reservation = existing or AIReservation(owner_id=owner, source_version_id=source_id)
            reservation.period, reservation.model, reservation.amount_micro_usd = period, model, amount
            reservation.status, reservation.actual_micro_usd = "reserved", None
            reservation.error_code, reservation.output = None, None
            if not existing:
                s.add(reservation)
            s.flush()
            return reservation.id, None

    def settle(self, reservation_id, actual=None, output=None, code=None, known_unbilled=False):
        with self.factory.begin() as s:
            ref = s.get(AIReservation, reservation_id)
            budget = s.scalar(select(AIBudget).where(AIBudget.owner_id == ref.owner_id, AIBudget.period == ref.period).with_for_update())
            reservation = s.scalar(select(AIReservation).where(AIReservation.id == reservation_id).with_for_update())
            if reservation.status != "reserved":
                return
            budget.reserved_micro_usd -= reservation.amount_micro_usd
            if known_unbilled:
                charged, status = 0, "failed"
            elif actual is None or actual < 0 or actual > reservation.amount_micro_usd:
                charged, status = reservation.amount_micro_usd, "unknown"
            else:
                charged, status = actual, "settled"
            budget.spent_micro_usd += charged
            reservation.actual_micro_usd, reservation.status = charged, status
            reservation.output, reservation.error_code = output, code
            budget.warning_80 = budget.warning_80 or budget.spent_micro_usd * 100 >= budget.limit_micro_usd * 80

    def status(self, owner):
        period = self.clock().astimezone(UTC).date().replace(day=1)
        with self.factory() as s:
            budget = s.get(AIBudget, (owner, period))
            if not budget:
                return {"period": period.isoformat(), "spent_micro_usd": 0, "reserved_micro_usd": 0, "warning_80": False}
            return {"period": period.isoformat(), "limit_micro_usd": budget.limit_micro_usd,
                    "spent_micro_usd": budget.spent_micro_usd, "reserved_micro_usd": budget.reserved_micro_usd,
                    "warning_80": budget.warning_80,
                    "blocked": budget.spent_micro_usd + budget.reserved_micro_usd >= budget.limit_micro_usd}
