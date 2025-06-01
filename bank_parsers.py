import requests
from bs4 import BeautifulSoup
from datetime import datetime
import random
import time

bank_cache = {}
CACHE_TTL = 1800

def parse_uralsub(currency='USD'):
    try:
        url = "https://www.sberbank.ru/ru/quotes/currencies"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        tables = soup.find_all('table', class_='kitt-table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) < 5:
                    continue
                    
                currency_cell = cells[0].get_text(strip=True)
                if currency in currency_cell:
                    buy_rate = cells[2].get_text(strip=True).replace(',', '.')
                    sell_rate = cells[3].get_text(strip=True).replace(',', '.')
                    
                    return {
                        'buy': float(buy_rate),
                        'sell': float(sell_rate),
                        'updated': datetime.now().strftime('%H:%M')
                    }
        return None
    except Exception as e:
        print(f"[Uralsub Parser] Ошибка: {e}")
        return None
def parse_vtb(currency='USD'):
    try:
        url = "https://www.vtb.ru/personal/platezhi-i-perevody/obmen-valjuty/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        table = soup.find('table', class_='rates-table')
        if not table:
            return None
            
        for row in table.find_all('tr'):
            currency_cell = row.find('span', class_='rates-table__code')
            if currency_cell and currency in currency_cell.text:
                buy_cell = row.find('td', class_='rates-table__buy')
                sell_cell = row.find('td', class_='rates-table__sell')
                
                if buy_cell and sell_cell:
                    buy_rate = buy_cell.find('span', class_='rates-table__value').text.replace(',', '.')
                    sell_rate = sell_cell.find('span', class_='rates-table__value').text.replace(',', '.')
                    
                    return {
                        'buy': float(buy_rate),
                        'sell': float(sell_rate),
                        'updated': datetime.now().strftime('%H:%M')
                    }
        return None
    except Exception as e:
        print(f"[VTB Parser] Ошибка: {e}")
        return None

def parse_tinkoff(currency='USD'):
    try:
        response = requests.get(
            'https://api.tinkoff.ru/v1/currency_rates', 
            timeout=10
        )
        data = response.json()
        
        for rate in data['payload']['rates']:
            if (rate['category'] == 'DepositPayments' and 
                rate['fromCurrency']['name'] == currency and
                rate['toCurrency']['name'] == 'RUB'):
                
                return {
                    'buy': rate['buy'],
                    'sell': rate['sell'],
                    'updated': datetime.now().strftime('%H:%M')
                }
        return None
    except Exception as e:
        print(f"[Tinkoff Parser] Ошибка: {e}")
        return None
def parse_alfabank(currency='USD'):
    try:
        url = "https://alfabank.ru/api/v1/scrooge/currencies/alfa-rates?currencyCode.in={}&rateType.in=rateCBRF,rateCard,rateCB,rateTBB,rateSB".format(currency)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
        }
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()

        for rate in data['data']:
            if rate['currencyCode'] == currency:
                if 'rate' in rate:
                    return {
                        'buy': rate['rate']['buy'],
                        'sell': rate['rate']['sell'],
                        'updated': datetime.now().strftime('%H:%M')
                    }
                for rate_type in rate['rates']:
                    if rate_type['rateType'] == 'rateCard':
                        return {
                            'buy': rate_type['buy']['value'],
                            'sell': rate_type['sell']['value'],
                            'updated': datetime.now().strftime('%H:%M')
                        }
        return None
    except Exception as e:
        print(f"[Alfabank Parser] Ошибка: {e}")
        return None

def get_bank_rates(currency='USD'):
    cache_key = f"rates_{currency}"
    
    if cache_key in bank_cache:
        cached_data, timestamp = bank_cache[cache_key]
        if time.time() - timestamp < CACHE_TTL:
            return cached_data

    parsers = [
        {'name': 'Уралсиб', 'parser': parse_uralsub},
        {'name': 'ВТБ', 'parser': parse_vtb},
        {'name': 'Тинькофф', 'parser': parse_tinkoff},
        {'name': 'Альфа-Банк', 'parser': parse_alfabank},
    ]
    
    results = []
    for bank in parsers:
        try:
            rates = bank['parser'](currency)
            if rates:
                results.append({
                    'name': bank['name'],
                    'buy': rates['buy'],
                    'sell': rates['sell'],
                    'updated': rates['updated'],
                    'currency': currency
                })
            time.sleep(0.5)
        except Exception as e:
            print(f"Ошибка при обработке банка {bank['name']}: {e}")
    
    if not results:
        results.append({
            'name': 'Данные временно недоступны',
            'buy': 0,
            'sell': 0,
            'updated': '-',
            'currency': currency
        })

    bank_cache[cache_key] = (results, time.time())
    return results