#!/usr/bin/env bash
# Fetch external assets (music + LUT) used by the demo cut scripts.
# Both are gitignored — re-run this after cloning to populate them.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p assets/music assets/luts

# Music: Kevin MacLeod "Impact Andante" — CC BY 4.0
# Attribution: "Impact Andante" Kevin MacLeod (incompetech.com), Licensed under
# Creative Commons: By Attribution 4.0 License, https://creativecommons.org/licenses/by/4.0/
if [ ! -f "assets/music/impact_andante_kevin_macleod.mp3" ]; then
    echo "Downloading music..."
    curl -sL -o "assets/music/impact_andante_kevin_macleod.mp3" \
        "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Impact%20Andante.mp3"
fi

# LUT: Sam Kolder-style teal-orange grade for Rec.709 input
# Source: aras-p/smol-cube on GitHub (MIT/Unlicense, included as test data)
if [ ! -f "assets/luts/teal_orange.cube" ]; then
    echo "Downloading LUT..."
    curl -sL -o "assets/luts/teal_orange.cube" \
        "https://raw.githubusercontent.com/aras-p/smol-cube/main/tests/luts/tinyglade-Sam_Kolder.cube"
fi

echo "Done. Assets:"
ls -la assets/music/ assets/luts/
