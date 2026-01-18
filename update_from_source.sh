#!/bin/bash
# Update script for synth-subnet
# This script fetches updates from the source project and merges them into your repository

set -e  # Exit on error

echo "🔄 Fetching updates from source project..."
git fetch upstream

echo "📥 Merging updates into main branch..."
git checkout main
git merge upstream/main

echo "📤 Pushing to your GitHub repository..."
git push origin main

echo "✅ Update complete!"
echo ""
echo "If you have local changes, you may need to resolve merge conflicts."
echo "To view any conflicts, run: git status"
