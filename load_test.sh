#!/bin/bash

# Endpoint URL
URL="http://nova-face-530279342.us-east-1.elb.amazonaws.com:5500/transform"

# Data file
DATA_FILE="@example.json"

# Content-Type
CONTENT_TYPE="application/json"

# Number of requests
REQUESTS=4

# Interval between requests in seconds
INTERVAL=1

# Output file
OUTPUT_FILE="load_test_results.csv"

# Create or clear the file
echo "Timestamp,Response Time (s),Response" > $OUTPUT_FILE

echo "Starting extended load test..."

# Function to make a request and log the result
send_request() {
  START=$(date +%s.%N)
  RESPONSE=$(curl -s -o response.tmp -w "%{http_code}" -X POST $URL -H "Content-Type: $CONTENT_TYPE" -d $DATA_FILE)
  END=$(date +%s.%N)
  RESPONSE_TIME=$(echo "$END - $START" | bc)
  TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
  if [ $RESPONSE -eq 200 ]; then
    RESPONSE_DATA=$(<response.tmp)
  else
    RESPONSE_DATA="Error: HTTP $RESPONSE"
  fi
  echo "$TIMESTAMP,$RESPONSE_TIME,$RESPONSE_DATA" >> $OUTPUT_FILE
  rm response.tmp
}

for ((i=1; i<=REQUESTS; i++))
do
  echo "Sending request $i"
  send_request
  sleep $INTERVAL
done

echo "Extended load test completed. Results saved to $OUTPUT_FILE."