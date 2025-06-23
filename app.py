from flask import Flask, render_template, request
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import requests
from datetime import datetime, timedelta
import os
import json
import time
import random
import numpy as np 
from bank_parsers import get_bank_rates
import pandas as pd
from collections import defaultdict
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)

MYSQL_CONFIG = {
    'user': os.getenv('MYSQL_USER', 'andrey'),
    'password': os.getenv('MYSQL_PASSWORD', 'zxc555ewq'),
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'database': os.getenv('MYSQL_DATABASE', 'currency_app'),
    'port': os.getenv('MYSQL_PORT', 3306),
    'ssl_disabled': True
}

ALPHA_VANTAGE_KEY = os.environ.get('ALPHA_VANTAGE_KEY', 'JDAB60C0396F3IRG')
ALPHA_VANTAGE_URL = 'https://www.alphavantage.co/query'

API_KEY = os.environ.get('EXCHANGE_API_KEY', '26cdbcfcb33ba430ba05d900')
BASE_URL = 'https://v6.exchangerate-api.com/v6/'
CURRENCIES = ['SGD', 'USD', 'EUR', 'GBP', 'JPY', 'CNY', 'RUB', 'AUD', 'CAD', 'CHF', 'INR']

CURRENCY_NAMES = {
    'SGD': 'Сингапурский доллар',
    'USD': 'Доллар США',
    'EUR': 'Евро',
    'GBP': 'Фунт стерлингов',
    'JPY': 'Японская иена',
    'CNY': 'Китайский юань',
    'RUB': 'Российский рубль',
    'AUD': 'Австралийский доллар',
    'CAD': 'Канадский доллар',
    'CHF': 'Швейцарский франк',
    'INR': 'Индийская рупия'
}

exchange_rates_cache = {'rates': {}, 'timestamp': 0}
historical_cache = {}
usd_cross_cache = defaultdict(dict)

def create_connection():
    try:
        connection = mysql.connector.connect(**MYSQL_CONFIG)
        return connection
    except Error as e:
        print(f"Ошибка подключения к MySQL: {e}")
        return None

def init_database():
    connection = create_connection()
    if connection is None:
        return
    
    try:
        cursor = connection.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS exchange_rates (
            id INT AUTO_INCREMENT PRIMARY KEY,
            from_currency VARCHAR(3) NOT NULL,
            to_currency VARCHAR(3) NOT NULL,
            rate FLOAT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY (from_currency, to_currency)
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS historical_rates (
            id INT AUTO_INCREMENT PRIMARY KEY,
            from_currency VARCHAR(3) NOT NULL,
            to_currency VARCHAR(3) NOT NULL,
            date DATE NOT NULL,
            rate FLOAT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY (from_currency, to_currency, date)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bank_rates (
            id INT AUTO_INCREMENT PRIMARY KEY,
            bank_name VARCHAR(100) NOT NULL,
            currency VARCHAR(3) NOT NULL,
            buy_rate FLOAT NOT NULL,
            sell_rate FLOAT NOT NULL,
            updated DATETIME NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY (bank_name, currency)
        )
        """)
        
        connection.commit()
        print("Таблицы успешно созданы")
        
    except Error as e:
        print(f"Ошибка при создании таблиц: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def save_exchange_rates_to_db(rates):
    connection = create_connection()
    if connection is None:
        return
    
    try:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM exchange_rates")

        for from_curr, to_currencies in rates.items():
            for to_curr, rate in to_currencies.items():
                cursor.execute("""
                INSERT INTO exchange_rates (from_currency, to_currency, rate)
                VALUES (%s, %s, %s)
                """, (from_curr, to_curr, rate))
        
        connection.commit()
        print("Курсы валют сохранены в БД")
        
    except Error as e:
        print(f"Ошибка сохранения курсов в БД: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def get_exchange_rates_from_db():
    connection = create_connection()
    if connection is None:
        return None
    
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT from_currency, to_currency, rate FROM exchange_rates")
        rows = cursor.fetchall()
        
        if not rows:
            return None
        
        rates = {}
        for row in rows:
            if row['from_currency'] not in rates:
                rates[row['from_currency']] = {}
            rates[row['from_currency']][row['to_currency']] = row['rate']
        
        return rates
        
    except Error as e:
        print(f"Ошибка получения курсов из БД: {e}")
        return None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def save_historical_rates_to_db(from_curr, to_curr, rates, dates):
    connection = create_connection()
    if connection is None:
        return
    
    try:
        cursor = connection.cursor()
        cursor.execute("""
        DELETE FROM historical_rates 
        WHERE from_currency = %s AND to_currency = %s
        """, (from_curr, to_curr))

        for date, rate in zip(dates, rates):
            cursor.execute("""
            INSERT INTO historical_rates (from_currency, to_currency, date, rate)
            VALUES (%s, %s, %s, %s)
            """, (from_curr, to_curr, date, rate))
        
        connection.commit()
        print(f"Исторические данные для {from_curr}/{to_curr} сохранены в БД")
        
    except Error as e:
        print(f"Ошибка сохранения исторических данных в БД: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def get_historical_rates_from_db(from_curr, to_curr, days=7):
    connection = create_connection()
    if connection is None:
        return None, None
    
    try:
        cursor = connection.cursor()
        cursor.execute("""
        SELECT date, rate 
        FROM historical_rates 
        WHERE from_currency = %s AND to_currency = %s 
        ORDER BY date DESC 
        LIMIT %s
        """, (from_curr, to_curr, days))
        
        rows = cursor.fetchall()
        
        if not rows:
            return None, None
        
        dates = []
        rates = []
        for row in rows:
            dates.append(row[0])
            rates.append(row[1])
        
        return rates, dates
        
    except Error as e:
        print(f"Ошибка получения исторических данных из БД: {e}")
        return None, None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def save_bank_rates_to_db(bank_rates):
    connection = create_connection()
    if connection is None:
        return
    
    try:
        cursor = connection.cursor()
        
        for bank in bank_rates:
            cursor.execute("""
            INSERT INTO bank_rates (bank_name, currency, buy_rate, sell_rate, updated)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                buy_rate = VALUES(buy_rate),
                sell_rate = VALUES(sell_rate),
                updated = VALUES(updated)
            """, (
                bank['name'], 
                bank['currency'], 
                bank['buy'], 
                bank['sell'], 
                bank['updated']
            ))
        
        connection.commit()
        print("Банковские курсы сохранены в БД")
        
    except Error as e:
        print(f"Ошибка сохранения банковских курсов в БД: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def get_bank_rates_from_db(currency):
    connection = create_connection()
    if connection is None:
        return None
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("""
        SELECT bank_name, currency, buy_rate, sell_rate, updated 
        FROM bank_rates 
        WHERE currency = %s 
          AND timestamp >= NOW() - INTERVAL 1 HOUR
        """, (currency,))
        
        rows = cursor.fetchall()
        
        if not rows:
            return None
        
        bank_rates = []
        for row in rows:
            bank_rates.append({
                'name': row['bank_name'],
                'currency': row['currency'],
                'buy': row['buy_rate'],
                'sell': row['sell_rate'],
                'updated': row['updated'].strftime('%d.%m.%Y %H:%M')
            })
        
        return bank_rates
        
    except Error as e:
        print(f"Ошибка получения банковских курсов из БД: {e}")
        return None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

init_database()

def fetch_exchange_rates():
    db_rates = get_exchange_rates_from_db()
    if db_rates:
        print("Используются курсы из БД")
        exchange_rates_cache['rates'] = db_rates
        exchange_rates_cache['timestamp'] = time.time()
        return db_rates
    
    print("Получение курсов из API")
    try:
        response = requests.get(f'{BASE_URL}{API_KEY}/latest/USD')
        data = response.json()
        
        if data['result'] == 'success':
            rates = data['conversion_rates']
            all_rates = {}
            for from_curr in CURRENCIES:
                all_rates[from_curr] = {}
                for to_curr in CURRENCIES:
                    if from_curr == to_curr:
                        all_rates[from_curr][to_curr] = 1.0
                    elif from_curr == 'USD':
                        all_rates[from_curr][to_curr] = rates.get(to_curr, 1.0)
                    else:
                        usd_to_target = rates.get(to_curr, 1.0)
                        usd_to_base = rates.get(from_curr, 1.0)
                        all_rates[from_curr][to_curr] = usd_to_target / usd_to_base

            exchange_rates_cache['rates'] = all_rates
            exchange_rates_cache['timestamp'] = time.time()
            save_exchange_rates_to_db(all_rates)
            return all_rates
    except Exception as e:
        print(f"Ошибка при получении курсов: {e}")

    return exchange_rates_cache['rates']

def fetch_direct_historical_range(from_curr, to_curr, days=7):
    try:
        params = {
            'function': 'FX_DAILY',
            'from_symbol': from_curr,
            'to_symbol': to_curr,
            'apikey': ALPHA_VANTAGE_KEY,
            'outputsize': 'compact' if days <= 100 else 'full',
            'datatype': 'json'
        }
        
        response = requests.get(ALPHA_VANTAGE_URL, params=params)
        data = response.json()
        
        if 'Note' in data:
            print(f"API Limit: {data['Note']}")
            return None, None
            
        if 'Time Series FX (Daily)' in data:
            series = data['Time Series FX (Daily)']
            sorted_dates = sorted(series.keys(), reverse=True)[:days]
            
            dates = []
            rates = []
            
            for date_str in sorted_dates:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                dates.append(date_obj)
                rates.append(float(series[date_str]['4. close']))
                
            return rates, dates

        print(f"API Error: {data.get('Information', 'Unknown error')}")
        return None, None
        
    except Exception as e:
        print(f"Direct historical error {from_curr}/{to_curr}: {e}")
        return None, None

def fetch_historical_range(from_curr, to_curr, days=7):
    db_rates, db_dates = get_historical_rates_from_db(from_curr, to_curr, days)
    if db_rates and db_dates:
        print(f"Используются исторические данные из БД для {from_curr}/{to_curr}")
        return db_rates, db_dates
    
    print(f"Получение исторических данных из API для {from_curr}/{to_curr}")
    rates, dates = fetch_direct_historical_range(from_curr, to_curr, days)

    if rates is None and from_curr != 'USD' and to_curr != 'USD':
        usd_rates1, usd_dates1 = fetch_historical_range(from_curr, 'USD', days)
        usd_rates2, usd_dates2 = fetch_historical_range(to_curr, 'USD', days)
        
        if usd_rates1 and usd_rates2:
            dict1 = dict(zip(usd_dates1, usd_rates1))
            dict2 = dict(zip(usd_dates2, usd_rates2))
            common_dates = sorted(set(usd_dates1) & set(usd_dates2), reverse=True)[:days]
            
            if common_dates:
                rates = []
                dates = common_dates
                for date in common_dates:
                    cross_rate = dict1[date] / dict2[date]
                    rates.append(cross_rate)

    if rates is not None:
        save_historical_rates_to_db(from_curr, to_curr, rates, dates)
        return rates, dates
    
    return None, None

def generate_exchange_chart(from_curr, to_curr):
    rates, dates = fetch_historical_range(from_curr, to_curr, days=7)
    
    if rates and dates:
        chart_title = f'Динамика курса {from_curr}/{to_curr} за 7 дней'
    else:
        base_rate = exchange_rates_cache['rates'].get(from_curr, {}).get(to_curr, 1.0)
        dates = [datetime.now().date() - timedelta(days=i) for i in range(6, -1, -1)]
        rates = [base_rate * (1 + random.uniform(-0.02, 0.02)) for _ in range(7)]

        for i in range(1, 7):
            volatility = 0.015 if 'JPY' in (from_curr, to_curr) else 0.008
            change = random.uniform(-volatility, volatility)
            rates[i] = rates[i-1] * (1 + change)

        rates[-1] = base_rate
        chart_title = f'Динамика курса {from_curr}/{to_curr}'

    plt.figure(figsize=(10, 6))
    plt.plot(dates, rates, marker='o', linestyle='-', color='#1F2261', 
             markersize=6, linewidth=2.5, markerfacecolor='white', markeredgewidth=1.5)
    plt.fill_between(dates, rates, min(rates)*0.99, color='#1F2261', alpha=0.1)

    if len(rates) > 1:
        x_dates = matplotlib.dates.date2num(dates)
        z = np.polyfit(x_dates, rates, 1)
        p = np.poly1d(z)
        plt.plot(dates, p(x_dates), 'r--', linewidth=1.5, alpha=0.7)
    
    plt.title(chart_title, fontsize=14, pad=20)
    plt.xlabel('Дата', fontsize=12)
    plt.ylabel(f'Курс {from_curr} к {to_curr}', fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.7)

    date_labels = [date.strftime('%d-%m') for date in dates]
    plt.xticks(dates, date_labels, rotation=15)

    if rates[0] != 0:
        change_percent = ((rates[-1] - rates[0]) / rates[0]) * 100
        change_text = f"Изменение: {change_percent:+.2f}%"
        change_color = 'green' if change_percent >= 0 else 'red'
        plt.annotate(change_text, xy=(0.95, 0.95), xycoords='axes fraction',
                    color=change_color, fontsize=12,
                    bbox=dict(boxstyle='round,pad=0.3', fc='white', ec=change_color, alpha=0.8))

    for i, (date, rate) in enumerate(zip(dates, rates)):
        if i == 0 or i == len(rates)-1 or i % 2 == 0:
            fmt = '.2f' if to_curr == 'RUB' or from_curr == 'RUB' else '.4f'
            plt.annotate(f'{rate:{fmt}}', 
                         xy=(date, rate),
                         xytext=(0, 10),
                         textcoords='offset points',
                         fontsize=9,
                         ha='center')
    
    plt.tight_layout()

    img_buf = BytesIO()
    plt.savefig(img_buf, format='png', dpi=100)
    img_buf.seek(0)
    img_data = base64.b64encode(img_buf.read()).decode('utf-8')
    plt.close()
    
    return img_data

@app.route('/', methods=['GET', 'POST'])
def index():
    exchange_rates = fetch_exchange_rates()
    
    if not exchange_rates:
        return "Ошибка получения данных. Пожалуйста, попробуйте позже.", 500

    from_currency = request.form.get('from_currency', 'SGD')
    to_currency = request.form.get('to_currency', 'USD')
    
    if request.form.get('swap') == '1':
        from_currency, to_currency = to_currency, from_currency
    
    try:
        amount = float(request.form.get('amount', 1000.00))
    except ValueError:
        amount = 1000.00

    rate = exchange_rates.get(from_currency, {}).get(to_currency, 1.0)
    converted_amount = round(amount * rate, 2)

    chart_img = generate_exchange_chart(from_currency, to_currency)

    update_time = datetime.now().strftime('%d.%m.%Y %H:%M')

    target_currency = from_currency if from_currency in ['USD', 'EUR'] else 'USD'
    
    banks = get_bank_rates_from_db(target_currency)
    
    if not banks:
        banks = get_bank_rates(target_currency)
        if banks:
            save_bank_rates_to_db(banks)
    
    if not banks:
        banks = [{
            'name': 'Данные временно недоступны',
            'buy': 0,
            'sell': 0,
            'updated': '-',
            'currency': target_currency
        }]

    return render_template(
        'index.html',
        from_currency=from_currency,
        to_currency=to_currency,
        amount=amount,
        converted_amount=converted_amount,
        rate=rate,
        chart_img=chart_img,
        update_time=update_time,
        currency_names=CURRENCY_NAMES,
        banks=banks,
        currencies=CURRENCIES,
        target_currency=target_currency
    )

if __name__ == '__main__':
    app.run(debug=True)
