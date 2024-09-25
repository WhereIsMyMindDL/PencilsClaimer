import asyncio
import aiohttp
import datetime
import secrets
import pandas as pd
from sys import stderr
from loguru import logger
from eth_account.account import Account
from eth_account.messages import encode_defunct

logger.remove()
logger.add(stderr,
           format="<lm>{time:HH:mm:ss}</lm> | <level>{level}</level> | <blue>{function}:{line}</blue> "
                  "| <lw>{message}</lw>")


class PencilsClaimer:
    def __init__(self, private_key: str, proxy: str, number_acc: int, bybit_uid: str, bybit_address: str) -> None:
        self.account = Account().from_key(private_key=private_key)
        self.proxy: str = f"http://{proxy}" if proxy is not None else None
        self.id: int = number_acc
        self.client, self.amount_tokens = None, 0
        self.bybit_uid = bybit_uid
        self.bybit_address = bybit_address

    async def create_message(self) -> str:
        output_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        output_datetime = datetime.datetime.strptime(output_date, "%Y-%m-%dT%H:%M:%S.%fZ")
        expiration_datetime = output_datetime + datetime.timedelta(minutes=3)
        expiration_time = expiration_datetime.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        message: str = f'pencilsprotocol.io wants you to sign in with your account: {self.account.address}\n\n' \
                       f'Please ensure that the domain above matches the URL of the current website.\n\n' \
                       f'Version: 1\n' \
                       f'Nonce: {secrets.token_hex(11)}\n' \
                       f'Issued At: {output_date}\n' \
                       f'Expiration Time: {expiration_time}'
        return message

    async def login(self) -> None:
        message = await PencilsClaimer.create_message(self)
        signature = self.account.sign_message(encode_defunct(text=message)).signature.hex()
        response: aiohttp.ClientResponse = await self.client.post(
            f'https://pencilsprotocol.io/api/login',
            json={
                'address': self.account.address,
                'msg': message,
                'signature': f'0x{signature}',
                'walletName': 'Rabby Wallet',
            },
            proxy=self.proxy
        )
        if response.status == 201:
            response_json: dict = await response.json()
            if response_json['code'] == 0:
                logger.success(f"{self.account.address} success login")
                return await PencilsClaimer.check_eligible(self)
        raise Exception(f'Login: response {response.text}')

    async def check_eligible(self) -> None:
        global total_tokens
        response: aiohttp.ClientResponse = await self.client.get(
            url=f'https://pencilsprotocol.io/api/vesting/airdrop/3',
            proxy=self.proxy
        )
        if response.status == 200:
            try:
                response_json: dict = await response.json()
            except Exception as e:
                logger.info(f"{self.account.address} not eligible")
                return
            if 0 < len(response_json) < 5:
                self.amount_tokens += float(response_json['token'])
                total_tokens += self.amount_tokens
                logger.success(f"{self.account.address} Congrats u eligible for {self.amount_tokens} tokens")
                return await PencilsClaimer.claim_on_cex(self)
            elif len(response_json) > 4:
                total_tokens += float(response_json['token'])
                logger.info(f"{self.account.address} already claimed {float(response_json['token'])} tokens")
                return
        # raise Exception(f'Check_eligible: response {response.text}')

    async def claim_on_cex(self) -> None:
        message = f'Event: Early Active Users Airdrop\n' \
                  f'UserDecision: CEX\n' \
                  f'Exchange: bybit\n' \
                  f'ExchangeUID: {self.bybit_uid}\n' \
                  f'ExchangeDepositAddress: {self.bybit_address}'
        signature = self.account.sign_message(encode_defunct(text=message)).signature.hex()

        response: aiohttp.ClientResponse = await self.client.post(
            f'https://pencilsprotocol.io/api/vesting/airdrop/userDecision/3',
            json={
                'userDecision': 'CEX',
                'exchange': 'bybit',
                'exchangeUID': self.bybit_uid,
                'exchangeDepositAddress': self.bybit_address,
                'signature': f'0x{signature}',
            },
            proxy=self.proxy
        )
        if response.status == 201:
            logger.success(f"{self.account.address} success claim to {self.bybit_address}")
            return
        raise Exception(f'Claim_on_cex: response {response.text}')

    async def claim(self) -> None:
        async with aiohttp.ClientSession(headers={
            'authority': 'pencilsprotocol.io',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://pencilsprotocol.io',
            'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/124.0.0.0 Safari/537.36',
        }) as client:
            self.client = client
            await PencilsClaimer.login(self)


async def start_follow(account: list, id_acc: int, semaphore) -> None:
    async with semaphore:
        acc = PencilsClaimer(private_key=account[0], proxy=account[3],
                             number_acc=id_acc, bybit_uid=account[1], bybit_address=account[2])

        try:

            await acc.claim()

        except Exception as e:
            logger.error(f'{id_acc} Failed: {str(e)}')


async def main() -> None:
    semaphore: asyncio.Semaphore = asyncio.Semaphore(10)

    tasks: list[asyncio.Task] = [
        asyncio.create_task(coro=start_follow(account=account, id_acc=idx, semaphore=semaphore))
        for idx, account in enumerate(accounts, start=1)
    ]
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    with open('accounts_data.xlsx', 'rb') as file:
        exel = pd.read_excel(file)
    total_tokens: float = 0
    accounts: list[list] = [
        [
            row["Private Key"], row["BybitUID"], row["BybitAddress"],
            row["Proxy"] if isinstance(row["Proxy"], str) else None
        ]
        for index, row in exel.iterrows()
    ]
    logger.info(f'My channel: https://t.me/CryptoMindYep')
    logger.info(f'Total wallets: {len(accounts)}\n')

    asyncio.run(main())

    logger.info(f'Total tokens: {total_tokens}')
    logger.success('The work completed')
    logger.info('Thx for donat: 0x5AfFeb5fcD283816ab4e926F380F9D0CBBA04d0e')
