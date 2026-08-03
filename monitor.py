# monitor.py
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import logging
from models import AddressInfo, Transaction
from clients import ExplorerClient
from services import TransactionAnalyzer
from notifications import TransactionHandler, MultiTelegramHandler

class ErgoTransactionMonitor:
    def __init__(
        self,
        explorer_client: ExplorerClient,
        transaction_handlers: List[TransactionHandler]
    ):
        self.explorer_client = explorer_client
        self.transaction_handlers = transaction_handlers
        self.watched_addresses: Dict[str, AddressInfo] = {}
        self.processed_mempool_txs: Set[str] = set()
        self.logger = logging.getLogger(self.__class__.__name__)

    async def check_transactions(self, address: str) -> List[Transaction]:
        address_info = self.watched_addresses[address]
        new_transactions = []

        try:
            transactions = await self.explorer_client.get_address_transactions(address)
            current_time = datetime.now()
            
            for tx in transactions:
                tx_id = tx.get('id')
                is_mempool = tx.get('mempool', False)
                
                # Only process unconfirmed mempool transactions
                if is_mempool and tx_id not in self.processed_mempool_txs:
                    self.processed_mempool_txs.add(tx_id)
                    
                    tx_time = datetime.fromtimestamp(tx.get('timestamp', 0) / 1000)
                    
                    if tx_time > address_info.last_check:
                        tx_details = await TransactionAnalyzer.extract_transaction_details(
                            tx, 
                            address,
                            self.explorer_client
                        )
                        
                        if abs(tx_details.value) > 0.0001 or tx_details.tokens:
                            new_transactions.append(tx_details)
                            
                            if len(self.processed_mempool_txs) > 100:
                                self.processed_mempool_txs = set(
                                    list(self.processed_mempool_txs)[-100:]
                                )
                elif not is_mempool:
                    # Skip confirmed transactions completely to save API calls and processing
                    continue
            
            if new_transactions or not transactions:
                self.watched_addresses[address] = AddressInfo(
                    address=address_info.address,
                    nickname=address_info.nickname,
                    last_check=current_time,
                    last_height=max(
                        [tx.get('height', 0) for tx in transactions[:1]] 
                        or [address_info.last_height]
                    )
                )
            
        except Exception as e:
            self.logger.error(f"Error checking transactions for {address}: {str(e)}")
        
        return new_transactions

    async def monitor_loop(self, check_interval: int = 60):
        self.logger.info("Starting mempool monitoring loop...")
        
        try:
            while True:
                for address in list(self.watched_addresses.keys()):
                    try:
                        transactions = await self.check_transactions(address)
                        
                        if transactions:
                            for tx in sorted(transactions, key=lambda x: x.timestamp):
                                for handler in self.transaction_handlers:
                                    await handler.handle_transaction(address, tx, self)
                                
                                if tx.from_address or tx.to_address:
                                    for other_addr, other_info in self.watched_addresses.items():
                                        if other_addr != address:
                                            other_addr_short = f"{other_addr[:10]}...{other_addr[-4:]}"
                                            
                                            if ((tx.from_address and other_addr_short in tx.from_address) or
                                                (tx.to_address and other_addr_short in tx.to_address)):
                                                
                                                original_tx_data = None
                                                for t in transactions:
                                                    if t.tx_id == tx.tx_id:
                                                        original_tx_data = next(
                                                            t for t in await self.explorer_client.get_address_transactions(address)
                                                            if t.get('id') == tx.tx_id
                                                        )
                                                        break
                                                
                                                if original_tx_data:
                                                    mirrored_tx = await TransactionAnalyzer.extract_transaction_details(
                                                        original_tx_data,
                                                        other_addr,
                                                        self.explorer_client
                                                    )
                                                    
                                                    for handler in self.transaction_handlers:
                                                        await handler.handle_transaction(
                                                            other_addr,
                                                            mirrored_tx,
                                                            self
                                                        )
                    
                    except Exception as e:
                        self.logger.error(f"Error processing address {address}: {str(e)}")
                
                await asyncio.sleep(check_interval)
        finally:
            await self.explorer_client.close_session()
            
    def add_address(self, address: str, nickname: Optional[str] = None, 
                    hours_lookback: int = 1):
        """Add address for mempool tracking"""
        if not address or len(address) < 40:
            raise ValueError(f"Invalid Ergo address format: {address}")
        
        lookback_time = datetime.now() - timedelta(hours=hours_lookback)
        lookback_time = lookback_time.replace(minute=0, second=0, microsecond=0)
        
        self.watched_addresses[address] = AddressInfo(
            address=address,
            nickname=nickname or address[:8],
            last_check=lookback_time,
            last_height=0
        )
        
        self.logger.info(
            f"Added address {nickname or address[:8]} to mempool monitoring list "
            f"with {hours_lookback}h lookback from {lookback_time}"
        )
