"""Paper-trading portfolio: an in-memory simulated account.

Tracks cash, open positions and realised PnL exactly as a real account would,
so the same engine code drives both paper and (via the exchange layer) live
trading. Fees and slippage are modelled so paper results aren't rose-tinted.
"""
from __future__ import annotations

from .models import Position, Side, Trade

# Conservative, realistic frictions for paper simulation.
TAKER_FEE = 0.0006      # 0.06% per side (typical spot taker)
SLIPPAGE = 0.0005      # 0.05% adverse fill assumption


class PaperPortfolio:
    def __init__(self, starting_balance: float):
        self.starting_balance = starting_balance
        self.cash = starting_balance
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []

    # --- Valuation ----------------------------------------------------------
    def equity(self, prices: dict[str, float]) -> float:
        total = self.cash
        for sym, pos in self.positions.items():
            price = prices.get(sym, pos.entry_price)
            # Position value = margin locked (entry cost) + unrealised PnL.
            total += pos.entry_price * pos.quantity + pos.unrealized_pnl(price)
        return total

    def realized_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    # --- Order execution (simulated) ---------------------------------------
    def open(self, symbol: str, side: Side, price: float, quantity: float,
             stop_loss: float, take_profit: float) -> Position | None:
        fill = price * (1 + SLIPPAGE) if side == Side.LONG else price * (1 - SLIPPAGE)
        cost = fill * quantity
        fee = cost * TAKER_FEE
        if cost + fee > self.cash:
            return None
        self.cash -= cost + fee
        pos = Position(symbol, side, fill, quantity, stop_loss, take_profit)
        self.positions[symbol] = pos
        return pos

    def close(self, symbol: str, price: float, reason: str) -> Trade | None:
        pos = self.positions.get(symbol)
        if pos is None:
            return None
        fill = price * (1 - SLIPPAGE) if pos.side == Side.LONG else price * (1 + SLIPPAGE)
        proceeds = fill * pos.quantity
        fee = proceeds * TAKER_FEE
        # Return entry cost + PnL to cash.
        self.cash += pos.entry_price * pos.quantity + pos.unrealized_pnl(fill) - fee
        pnl = pos.unrealized_pnl(fill) - fee
        cost_basis = pos.entry_price * pos.quantity
        trade = Trade(
            symbol=symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=fill,
            quantity=pos.quantity,
            pnl=pnl,
            pnl_pct=(pnl / cost_basis * 100) if cost_basis else 0.0,
            reason=reason,
            opened_at=pos.opened_at,
        )
        self.trades.append(trade)
        del self.positions[symbol]
        return trade

    # --- Stats --------------------------------------------------------------
    def stats(self, prices: dict[str, float]) -> dict:
        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]
        equity = self.equity(prices)
        gross_win = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        return {
            "equity": equity,
            "cash": self.cash,
            "starting_balance": self.starting_balance,
            "total_return_pct": (equity / self.starting_balance - 1) * 100,
            "realized_pnl": self.realized_pnl(),
            "open_positions": len(self.positions),
            "total_trades": len(self.trades),
            "win_rate": (len(wins) / len(self.trades) * 100) if self.trades else 0.0,
            "profit_factor": (gross_win / gross_loss) if gross_loss else 0.0,
        }
