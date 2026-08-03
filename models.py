# models.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

@dataclass
class Token:
    token_id: str
    amount: int
    name: Optional[str] = None
    decimals: Optional[int] = None
    
    def get_formatted_amount(self) -> str:
        """Get amount formatted with proper decimals"""
        # Handle tokens with 0 decimals or unknown decimals cleanly
        if self.decimals is None or self.decimals == 0:
            return f"{'-' if self.amount < 0 else ''}{abs(self.amount)}"
        
        amount_str = str(abs(self.amount)).zfill(self.decimals + 1)
        int_part = amount_str[:-self.decimals] if len(amount_str) > self.decimals else "0"
        dec_part = amount_str[-self.decimals:]
        
        formatted = f"{int_part}"
        if dec_part:
            formatted += f".{dec_part.rstrip('0')}"
            if formatted.endswith('.'):
                formatted = formatted[:-1]
        
        return f"{'-' if self.amount < 0 else ''}{formatted}"

@dataclass
class Transaction:
    tx_type: str
    value: float
    tokens: List[Token]
    tx_id: str
    timestamp: datetime
    fee: float = 0.0
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    block: Optional[int] = None
    status: str = "unknown"

@dataclass
class AddressInfo:
    address: str
    nickname: str
    last_check: datetime
    last_height: int
