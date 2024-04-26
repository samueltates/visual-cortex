import asyncio
import aiohttp
import csv
import time
from datetime import datetime

URL = "http://nova-face-530279342.us-east-1.elb.amazonaws.com:5500/transform"
JSON_FILE = 'example.json'
REQUESTS = 4
RESULTS_FILE = 'async_load_test_results.csv'
INTERVAL_BETWEEN_REQUESTS = 30  # seconds

async def make_delayed_request(session, data, i, delay):
    await asyncio.sleep(delay)
    print(f"Sending request {i+1} after {delay}s delay")
    start_time = time.time()
    async with session.post(URL, data=data, headers={"Content-Type": "application/json"}) as response:
        resp_time = time.time() - start_time
        resp_text = await response.text()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"Request {i+1} completed. Response Time: {resp_time}s")
        return {'timestamp': timestamp, 'response_time': resp_time, 'response_data': resp_text[:100]}

async def main():
    with open(JSON_FILE, 'r') as json_file:
        data = json_file.read()
    async with aiohttp.ClientSession() as session:
        tasks = [make_delayed_request(session, data, i, i * INTERVAL_BETWEEN_REQUESTS) for i in range(REQUESTS)]
        results = await asyncio.gather(*tasks)
        with open(RESULTS_FILE, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Timestamp', 'Response Time (s)', 'Response Data'])
            for result in results:
                writer.writerow([result['timestamp'], result['response_time'], result['response_data']])

if __name__ == '__main__':
    asyncio.run(main())