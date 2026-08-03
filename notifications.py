# notifications.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Optional, List, Dict
import logging
from models import Transaction
import aiohttp

class TransactionHandler(Protocol):
    async def handle_transaction(self, address: str, transaction: Transaction) -> None:
        pass

class LogHandler(TransactionHandler):
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    async def handle_transaction(self, address: str, transaction: Transaction, monitor: ErgoTransactionMonitor) -> None:
        """Handle log transaction notification matching requested format"""
        wallet_name = next((info.nickname for info in monitor.watched_addresses.values() if info.address == address), address[:8])
        
        if transaction.value < 0:
            header = f'➜ Outgoing TX from "{wallet_name}"'
        elif transaction.value > 0:
            header = f'Incoming TX to "{wallet_name}"'
        else:
            header = f'🔄 Mixed TX for "{wallet_name}"'
            
        message = [header]
        
        if transaction.value != 0:
            sign = "+" if transaction.value > 0 else "-"
            val_str = f"{abs(transaction.value):.8f}".rstrip('0').rstrip('.')
            message.append(f"{sign} {val_str} ERG".strip())
            
        for token in sorted(transaction.tokens, key=lambda x: abs(x.amount), reverse=True):
            token_name = token.name or f"[{token.token_id[:12]}...]"
            formatted_amount = token.get_formatted_amount().lstrip('-')
            sign = "+" if token.amount > 0 else "-"
            message.append(f"{sign} {formatted_amount} {token_name}")
            
        message.append(f"https://ergexplorer.com/transactions#{transaction.tx_id}")
        
        self.logger.info("\n".join(message) + "\n")


@dataclass
class TelegramDestination:
    chat_id: str
    topic_id: Optional[int] = None
    
    def __post_init__(self):
        # Keeps your chat_id clean and respects whatever is set in config (no forced -100)
        self.chat_id = str(self.chat_id).strip()

@dataclass
class TelegramConfig:
    destinations: List[TelegramDestination]

class MultiTelegramHandler(TransactionHandler):
    def __init__(self, bot_token: str, address_configs: Dict[str, TelegramConfig], default_chat_id: Optional[str] = None):
        self.bot_token = bot_token
        self.address_configs = address_configs
        self.default_chat_id = default_chat_id
        if default_chat_id:
            self.default_destination = TelegramDestination(chat_id=default_chat_id)
        else:
            self.default_destination = None
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session: Optional[aiohttp.ClientSession] = None

    async def init_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()

    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None

    def get_destinations_for_address(self, address: str) -> List[TelegramDestination]:
        destinations = []
        if address in self.address_configs:
            destinations.extend(self.address_configs[address].destinations)
        if not destinations and self.default_destination:
            destinations.append(self.default_destination)
        return destinations

    async def handle_transaction(self, address: str, transaction: Transaction, monitor: ErgoTransactionMonitor) -> None:
        wallet_name = next((info.nickname for info in monitor.watched_addresses.values() if info.address == address), address[:8])
        
        if transaction.value < 0:
            header = f'➜ Outgoing TX from "{wallet_name}"'
        elif transaction.value > 0:
            header = f'Incoming TX to "{wallet_name}"'
        else:
            header = f'🔄 Mixed TX for "{wallet_name}"'
            
        message = [header]
        
        if transaction.value != 0:
            sign = "+" if transaction.value > 0 else "-"
            val_str = f"{abs(transaction.value):.8f}".rstrip('0').rstrip('.')
            message.append(f"{sign} {val_str} ERG")
            
        for token in sorted(transaction.tokens, key=lambda x: abs(x.amount), reverse=True):
            token_name = token.name or f"[{token.token_id[:12]}...]"
            formatted_amount = token.get_formatted_amount().lstrip('-')
            sign = "+" if token.amount > 0 else "-"
            message.append(f"{sign} {formatted_amount} {token_name}")
            
        message.append(f"\nhttps://ergexplorer.com/transactions#{transaction.tx_id}")

        message_text = "\n".join(message)
        destinations = self.get_destinations_for_address(address)
        
        for dest in destinations:
            try:
                success = await self.send_message(message_text, dest)
                if not success:
                    self.logger.error(f"Failed to send message to chat ID: {dest.chat_id}")
            except Exception as e:
                self.logger.error(f"Error sending message to chat ID {dest.chat_id}: {str(e)}")

    async def send_message(self, text: str, destination: TelegramDestination) -> bool:
        try:
            await self.init_session()
            url = f"{self.base_url}/sendMessage"
            
            # Using plain text (no Markdown parse_mode) to ensure default text sizing and avoid bugs
            payload = {
                "chat_id": destination.chat_id,
                "text": text,
                "disable_web_page_preview": True
            }
            
            if destination.topic_id is not None:
                payload["message_thread_id"] = int(destination.topic_id)
            
            async with self.session.post(url, json=payload) as response:
                response_data = await response.json()
                if response.status == 200 and response_data.get('ok'):
                    return True
                
                error_msg = response_data.get('description', 'Unknown error')
                self.logger.error(f"Failed to send Telegram message. Status: {response.status}, Error: {error_msg}")
                return False
                        
        except Exception as e:
            self.logger.error(f"Error sending Telegram message: {str(e)}", exc_info=True)
            return False
