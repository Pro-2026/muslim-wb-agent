from dataclasses import dataclass
from enum import Enum


class BidAction(str, Enum):
    increase = "increase"
    decrease = "decrease"
    keep = "keep"


@dataclass
class BidRecommendation:
    action: BidAction
    current_bid: int
    new_bid: int
    reason: str


# Настройки — потом вынести в .env или таблицу
MIN_BID = 50          # минимальная ставка (руб)
MAX_BID = 1000        # потолок ставки (руб)
STEP_UP = 50          # шаг повышения (руб)
STEP_DOWN = 30        # шаг снижения (руб)

TARGET_CTR = 0.03     # целевой CTR (3%)
TARGET_CPO = 500      # целевой CPO (руб)
MIN_CLICKS = 5        # минимум кликов для принятия решения
MIN_VIEWS = 100       # минимум показов для принятия решения


def calculate_bid_action(
    current_bid: int,
    views: int,
    clicks: int,
    orders: int,
    spend: float,
) -> BidRecommendation:
    """
    Чистая логика без LLM. Правила из регламента:
    - Мало данных → keep
    - CTR ниже порога → снижаем ставку
    - CPO выше порога → снижаем ставку
    - CTR выше порога и CPO в норме → повышаем
    - Всё в норме → keep
    """
    if views < MIN_VIEWS or clicks < MIN_CLICKS:
        return BidRecommendation(
            action=BidAction.keep,
            current_bid=current_bid,
            new_bid=current_bid,
            reason=f"Мало данных (показов: {views}, кликов: {clicks}) — ждём накопления",
        )

    ctr = clicks / views if views else 0.0
    cpo = spend / orders if orders else float("inf")

    if cpo > TARGET_CPO * 1.5:
        new_bid = max(MIN_BID, current_bid - STEP_DOWN)
        return BidRecommendation(
            action=BidAction.decrease,
            current_bid=current_bid,
            new_bid=new_bid,
            reason=f"CPO {cpo:.0f}р превышает цель {TARGET_CPO}р — снижаем ставку",
        )

    if ctr < TARGET_CTR * 0.5:
        new_bid = max(MIN_BID, current_bid - STEP_DOWN)
        return BidRecommendation(
            action=BidAction.decrease,
            current_bid=current_bid,
            new_bid=new_bid,
            reason=f"CTR {ctr:.2%} сильно ниже цели {TARGET_CTR:.2%} — снижаем ставку",
        )

    if ctr >= TARGET_CTR and cpo <= TARGET_CPO:
        new_bid = min(MAX_BID, current_bid + STEP_UP)
        return BidRecommendation(
            action=BidAction.increase,
            current_bid=current_bid,
            new_bid=new_bid,
            reason=f"CTR {ctr:.2%} и CPO {cpo:.0f}р в норме — повышаем ставку",
        )

    return BidRecommendation(
        action=BidAction.keep,
        current_bid=current_bid,
        new_bid=current_bid,
        reason=f"CTR {ctr:.2%}, CPO {cpo:.0f}р — держим ставку",
    )
