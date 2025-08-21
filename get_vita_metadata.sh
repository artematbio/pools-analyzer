#!/bin/bash

# VITA Token Metadata Fetch Script
# Based on Alchemy API documentation: https://www.alchemy.com/docs/how-to-get-token-metadata
# VITA Contract Address: 0x81f8f0bb1cb2a06649e51913a151f0e7ef6fa321 (Ethereum)

echo "🔍 Fetching VITA token metadata from Alchemy API..."
echo ""

# Check if ALCHEMY_API_KEY is set
if [ -z "$ALCHEMY_API_KEY" ]; then
    echo "⚠️  ALCHEMY_API_KEY environment variable not set."
    echo "   Set it with: export ALCHEMY_API_KEY='your_api_key_here'"
    echo ""
    echo "🔄 Using fallback key for demonstration..."
    ALCHEMY_API_KEY="Hkg1Oi9c8x3JEiXj2cL62"
fi

# Make the API request
curl -X POST \
  "https://eth-mainnet.g.alchemy.com/v2/${ALCHEMY_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "alchemy_getTokenMetadata",
    "params": ["0x81f8f0bb1cb2a06649e51913a151f0e7ef6fa321"],
    "id": 42
  }' | jq .

echo ""
echo "✅ Request completed!"
