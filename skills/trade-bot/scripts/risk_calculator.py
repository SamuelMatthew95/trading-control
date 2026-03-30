"""
Risk Calculator Script
Position sizing and risk management for automated trading
"""

from typing import Any


class RiskCalculator:
    """Risk management and position sizing calculator"""

    def __init__(self):
        self.risk_limits = {
            "max_position_size": 0.05,  # 5% max per position
            "max_portfolio_risk": 0.02,  # 2% max portfolio risk per trade
            "max_drawdown": 0.15,  # 15% max drawdown
            "volatility_target": 0.20,  # 20% annual volatility target
            "min_risk_reward": 2.0,  # Minimum 2:1 risk/reward ratio
        }

    def calculate_position_size(
        self,
        account_balance: float,
        stop_loss_pct: float,
        entry_price: float,
        portfolio_risk: float = None,
    ) -> dict[str, Any]:
        """
        Calculate optimal position size based on risk parameters

        Args:
            account_balance: Total account balance
            stop_loss_pct: Stop loss percentage (e.g., 0.02 for 2%)
            entry_price: Entry price per share/contract
            portfolio_risk: Current portfolio risk exposure (optional)

        Returns:
            Dictionary with position sizing and risk metrics
        """

        # Calculate maximum risk per trade
        max_risk_per_trade = account_balance * self.risk_limits["max_portfolio_risk"]

        # Calculate position size based on stop loss
        risk_per_share = entry_price * stop_loss_pct
        max_shares = int(max_risk_per_trade / risk_per_share)

        # Calculate position value
        position_value = max_shares * entry_price
        position_size_pct = position_value / account_balance

        # Apply maximum position size limit
        if position_size_pct > self.risk_limits["max_position_size"]:
            position_size_pct = self.risk_limits["max_position_size"]
            max_shares = int((account_balance * position_size_pct) / entry_price)
            position_value = max_shares * entry_price

        # Calculate actual risk
        actual_risk = position_value * stop_loss_pct
        risk_pct_of_account = actual_risk / account_balance

        return {
            "max_shares": max_shares,
            "position_value": position_value,
            "position_size_pct": position_size_pct,
            "actual_risk_amount": actual_risk,
            "risk_pct_of_account": risk_pct_of_account,
            "stop_loss_amount": entry_price * stop_loss_pct,
            "recommended": risk_pct_of_account <= self.risk_limits["max_portfolio_risk"],
        }

    def calculate_stop_loss(
        self,
        entry_price: float,
        signal_strength: float,
        atr: float = None,
        volatility: float = None,
    ) -> dict[str, Any]:
        """
        Calculate optimal stop loss level

        Args:
            entry_price: Entry price
            signal_strength: Signal strength (0-1)
            atr: Average True Range (optional)
            volatility: Price volatility (optional)

        Returns:
            Dictionary with stop loss calculations
        """

        # Base stop loss percentage
        base_stop_pct = 0.02  # 2% base stop loss

        # Adjust based on signal strength
        if signal_strength > 0.8:
            stop_multiplier = 1.5  # Wider stop for strong signals
        elif signal_strength > 0.6:
            stop_multiplier = 1.2
        elif signal_strength < 0.4:
            stop_multiplier = 0.8  # Tighter stop for weak signals
        else:
            stop_multiplier = 1.0

        # Use ATR if available
        if atr:
            stop_distance = atr * 2.0 * stop_multiplier
            stop_loss_pct = stop_distance / entry_price
        elif volatility:
            # Use volatility to adjust stop loss
            vol_adjusted_stop = base_stop_pct * (volatility / 0.20) * stop_multiplier
            stop_loss_pct = min(vol_adjusted_stop, 0.05)  # Max 5% stop loss
        else:
            stop_loss_pct = base_stop_pct * stop_multiplier

        stop_loss_price = entry_price * (1 - stop_loss_pct)

        return {
            "stop_loss_price": stop_loss_price,
            "stop_loss_pct": stop_loss_pct,
            "stop_distance": entry_price - stop_loss_price,
            "multiplier_used": stop_multiplier,
        }

    def assess_portfolio_risk(
        self, positions: dict[str, dict[str, Any]], account_balance: float
    ) -> dict[str, Any]:
        """
        Assess overall portfolio risk

        Args:
            positions: Dictionary of positions with size and entry info
            account_balance: Total account balance

        Returns:
            Portfolio risk assessment
        """

        total_position_value = 0
        total_unrealized_pnl = 0
        max_concentration = 0

        for _symbol, position in positions.items():
            position_value = position.get("value", 0)
            unrealized_pnl = position.get("unrealized_pnl", 0)

            total_position_value += position_value
            total_unrealized_pnl += unrealized_pnl

            # Calculate concentration
            concentration = position_value / account_balance if account_balance > 0 else 0
            max_concentration = max(max_concentration, concentration)

        # Calculate portfolio metrics
        portfolio_exposure = total_position_value / account_balance if account_balance > 0 else 0
        available_cash = account_balance - total_position_value
        total_return = total_unrealized_pnl / account_balance if account_balance > 0 else 0

        # Risk assessment
        risk_alerts = []
        if portfolio_exposure > 0.95:
            risk_alerts.append("High portfolio exposure")
        if max_concentration > self.risk_limits["max_position_size"]:
            risk_alerts.append(f"High concentration in single position: {max_concentration:.2%}")
        if total_return < -self.risk_limits["max_drawdown"]:
            risk_alerts.append(f"Portfolio drawdown exceeded: {total_return:.2%}")

        risk_level = "HIGH" if len(risk_alerts) > 2 else "MEDIUM" if risk_alerts else "LOW"

        return {
            "total_position_value": total_position_value,
            "portfolio_exposure": portfolio_exposure,
            "available_cash": available_cash,
            "max_concentration": max_concentration,
            "total_unrealized_pnl": total_unrealized_pnl,
            "total_return_pct": total_return,
            "risk_alerts": risk_alerts,
            "risk_level": risk_level,
        }

    def validate_risk_reward(
        self, entry_price: float, target_price: float, stop_loss: float
    ) -> dict[str, Any]:
        """
        Validate risk/reward ratio meets minimum requirements

        Args:
            entry_price: Entry price
            target_price: Take profit target
            stop_loss: Stop loss price

        Returns:
            Risk/reward validation
        """

        # Calculate potential profit and loss
        potential_profit = abs(target_price - entry_price)
        potential_loss = abs(entry_price - stop_loss)

        # Calculate risk/reward ratio
        risk_reward_ratio = potential_profit / potential_loss if potential_loss > 0 else 0

        # Validate minimum ratio
        meets_minimum = risk_reward_ratio >= self.risk_limits["min_risk_reward"]

        # Calculate percentages
        profit_pct = (potential_profit / entry_price) * 100
        loss_pct = (potential_loss / entry_price) * 100

        return {
            "potential_profit": potential_profit,
            "potential_loss": potential_loss,
            "risk_reward_ratio": risk_reward_ratio,
            "profit_pct": profit_pct,
            "loss_pct": loss_pct,
            "meets_minimum": meets_minimum,
            "minimum_required": self.risk_limits["min_risk_reward"],
        }
