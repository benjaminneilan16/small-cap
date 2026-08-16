name: Bygg universum

# Kör manuellt från GitHubs Actions-flik när du vill uppdatera listan,
# eller automatiskt en gång i månaden — bolagslistorna ändras sällan.
# Bygger BÅDA marknaderna i samma körning.
on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 1 * *"

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Hämta koden
        uses: actions/checkout@v4
      - name: Sätt upp Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Installera beroenden
        run: pip install -r requirements.txt
      - name: Bygg svenska universumet
        run: python build_universe.py --market se
      - name: Bygg amerikanska universumet
        run: python build_universe.py --market us
      - name: Spara resultatet
        run: |
          git config user.name "github-actions"
          git config user.email "github-actions@github.com"
          git add universe.txt unresolved.txt universe_us.txt unresolved_us.txt
          if git diff --staged --quiet; then
            echo "Ingen förändring i universumen"
          else
            git commit -m "Uppdaterar universum ($(date -u +'%Y-%m-%d'))"
            git checkout -- . 2>/dev/null || true
            git pull --rebase -X theirs
            git push
          fi
