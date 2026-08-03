# services.py
from __future__ import annotations
from typing import Dict, List, Set, Tuple, Optional, DefaultDict
from collections import defaultdict
import logging
from datetime import datetime
from models import Token, Transaction

class TokenInfoCache:
    """Cache for token information to avoid repeated API calls"""
    _cache: Dict[str, Dict] = {}
    _logger = logging.getLogger("TokenInfoCache")

    @classmethod
    async def get_token_info(cls, explorer_client: ExplorerClient, token_id: str) -> Dict:
        if token_id not in cls._cache:
            try:
                url = f"{explorer_client.explorer_url}/tokens/{token_id}"
                token_info = await explorer_client._make_request(url)
                cls._cache[token_id] = token_info if token_info else {"decimals": 0}
            except Exception as e:
                cls._logger.error(f"Error fetching token info for {token_id}: {str(e)}")
                cls._cache[token_id] = {"decimals": 0}
        return cls._cache[token_id]

    @classmethod
    async def get_token_decimals(cls, explorer_client: ExplorerClient, token_id: str) -> int:
        token_info = await cls.get_token_info(explorer_client, token_id)
        return token_info.get("decimals", 0)

class TransactionAnalyzer:
    @staticmethod
    def determine_transaction_type(tx: Dict, address: str) -> str:
        our_input_boxes = [box for box in tx.get('inputs', []) if box.get('address') == address]
        our_output_boxes = [box for box in tx.get('outputs', []) if box.get('address') == address]
        
        if our_input_boxes and our_output_boxes:
            return "Mixed"
        elif our_input_boxes:
            return "Out"
        elif our_output_boxes:
            return "In"
        return "Unknown"

    @staticmethod
    async def extract_transaction_details(tx: Dict, address: str, explorer_client: ExplorerClient) -> Transaction:
        inputs = tx.get('inputs', [])
        outputs = tx.get('outputs', [])
        
        our_input_boxes = [box for box in inputs if box.get('address') == address]
        our_output_boxes = [box for box in outputs if box.get('address') == address]
        
        tx_type = TransactionAnalyzer.determine_transaction_type(tx, address)
        
        input_value = sum(box.get('value', 0) / 1e9 for box in our_input_boxes)
        output_value = sum(box.get('value', 0) / 1e9 for box in our_output_boxes)
        
        if tx_type == "Out":
            value = -(input_value - output_value)
        elif tx_type == "In":
            value = output_value
        else:  # Mixed
            value = output_value - input_value
        
        token_changes: DefaultDict[str, Dict] = defaultdict(
            lambda: {"amount": 0, "name": None, "decimals": None}
        )
        
        for box in our_input_boxes:
            for asset in box.get('assets', []):
                token_id = asset.get('tokenId')
                amount = asset.get('amount', 0)
                token_changes[token_id]["amount"] -= amount
                if not token_changes[token_id]["name"]:
                    token_changes[token_id]["name"] = asset.get('name')
        
        for box in our_output_boxes:
            for asset in box.get('assets', []):
                token_id = asset.get('tokenId')
                amount = asset.get('amount', 0)
                token_changes[token_id]["amount"] += amount
                if not token_changes[token_id]["name"]:
                    token_changes[token_id]["name"] = asset.get('name')
        
        tokens = []
        for token_id, info in token_changes.items():
            if info["amount"] != 0:
                decimals = await TokenInfoCache.get_token_decimals(explorer_client, token_id)
                tokens.append(Token(
                    token_id=token_id,
                    amount=info["amount"],
                    name=info["name"],
                    decimals=decimals
                ))
        
        return Transaction(
            tx_type=tx_type,
            value=value,
            tokens=tokens,
            tx_id=tx.get('id'),
            timestamp=datetime.fromtimestamp(tx.get('timestamp', 0) / 1000)
        )
