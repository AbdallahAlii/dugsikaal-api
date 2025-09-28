# stock/engine/valuation/fifo.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Tuple


@dataclass
class Layer:
    qty: Decimal
    rate: Decimal


def push_layer(queue: List[Layer], qty: Decimal, rate: Decimal) -> None:
    queue.append(Layer(qty=qty, rate=rate))


def consume(queue: List[Layer], qty: Decimal) -> Tuple[List[Layer], Decimal]:
    """
    Consume qty from FIFO queue, returning (layers_consumed, total_cost).
    """
    to_consume = qty
    consumed: List[Layer] = []
    cost = Decimal("0")
    while to_consume > 0 and queue:
        layer = queue[0]
        take = min(layer.qty, to_consume)
        cost += take * layer.rate
        consumed.append(Layer(qty=take, rate=layer.rate))
        layer.qty -= take
        to_consume -= take
        if layer.qty == 0:
            queue.pop(0)
    if to_consume > 0:
        # negative stock depending on policy; for now, assume allowed with last rate or zero
        cost += to_consume * (queue[0].rate if queue else Decimal("0"))
        consumed.append(Layer(qty=to_consume, rate=(queue[0].rate if queue else Decimal("0"))))
        to_consume = Decimal("0")
    return consumed, cost


def revalue_layers(queue: List[Layer], delta_value: Decimal) -> None:
    """
    Spread delta_value over existing layers proportionally.
    """
    total_qty = sum(l.qty for l in queue)
    if total_qty == 0:
        return
    per_unit_delta = delta_value / total_qty
    for l in queue:
        l.rate = l.rate + per_unit_delta
