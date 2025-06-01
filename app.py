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

app = Flask(__name__)

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

def fetch_exchange_rates():
    if time.time() - exchange_rates_cache['timestamp'] < 1800 and exchange_rates_cache['rates']:
        return exchange_rates_cache['rates']
    
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
            return all_rates
    except Exception as e:
        print(f"Ошибка при получении курсов: {e}")

    return exchange_rates_cache['rates']

def fetch_historical_range(from_curr, to_curr, days=7):

    cache_key = f"{from_curr}_{to_curr}_{days}"

    if cache_key in historical_cache:
        cached_data = historical_cache[cache_key]
        if time.time() - cached_data['timestamp'] < 3600:
            return cached_data['rates'], cached_data['dates']
    
    try:
        params = {
            'function': 'FX_DAILY',
            'from_symbol': from_curr,
            'to_symbol': to_curr,
            'apikey': ALPHA_VANTAGE_KEY,
            'outputsize': 'compact',
            'datatype': 'json'
        }
        
        response = requests.get(ALPHA_VANTAGE_URL, params=params)
        data = response.json()
        
        if 'Time Series FX (Daily)' in data:
            series = data['Time Series FX (Daily)']

            all_dates = sorted(series.keys(), reverse=True)
            selected_dates = all_dates[:days]
            
            dates = []
            rates = []
            
            for date_str in selected_dates:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                dates.append(date_obj)
                rates.append(float(series[date_str]['4. close']))

            current_rate = exchange_rates_cache['rates'].get(from_curr, {}).get(to_curr)
            today = datetime.now().date()

            if dates and dates[0] != today and current_rate:
                dates.insert(0, today)
                rates.insert(0, current_rate)

            cache_entry = {
                'rates': rates,
                'dates': dates,
                'timestamp': time.time()
            }
            historical_cache[cache_key] = cache_entry
            return rates, dates

        print(f"API Error: {data.get('Note', data.get('Information', 'Unknown error'))}")
        
    except Exception as e:
        print(f"Ошибка при получении исторических данных: {e}")
    
    return None, None

def generate_exchange_chart(from_curr, to_curr):

    result = fetch_historical_range(from_curr, to_curr, days=7)
    
    if result and result[0] is not None and result[1] is not None:
        rates, dates = result
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
        chart_title = f'Имитация курса {from_curr}/{to_curr} (реальные данные недоступны)'

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

    date_labels = [date.strftime('%d.%m') for date in dates]
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
    banks = get_bank_rates(target_currency)
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