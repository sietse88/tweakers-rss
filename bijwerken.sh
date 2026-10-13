#!/usr/bin/env bash
# Werkt de feed elk kwartier bij, LOOPTIJD_MINUTEN lang (standaard 330 = 5,5 uur).
#
# GitHub voert de geplande runs maar een paar keer per dag uit (bij Tweakers
# 4 à 6 keer, ook met vier starts per uur in de planning). Door elke run lang
# door te laten lopen en tussentijds op te halen, wordt toch het grootste deel
# van de dag gekeken, en staat het dagbestand kort na 17:00 klaar.
#
# Er wordt alleen gecommit als de artikelen veranderen (nieuw artikel, andere
# tekst, dagbestand), niet als alleen lastBuildDate verschuift. Aan het eind
# volgt nog één commit, voor het geval een push eerder mislukte.
set -u

LOOPTIJD_MINUTEN="${LOOPTIJD_MINUTEN:-330}"
INTERVAL_MINUTEN="${INTERVAL_MINUTEN:-15}"
BESTANDEN="docs/feed.xml archive.json dagen/"

# Wat de lezer ziet: de feed zonder bouwtijd, plus de dagbestanden.
inhoud() {
  grep -v '<lastBuildDate>' docs/feed.xml 2>/dev/null
  cat dagen/* 2>/dev/null
}

commit_en_push() {
  git add $BESTANDEN
  if ! git diff --staged --quiet; then
    git commit -q -m "Feed bijgewerkt ($(date -u +'%Y-%m-%d %H:%M UTC'))"
  fi
  # Ook een eerder mislukte push wordt hier alsnog geprobeerd.
  for poging in 1 2 3; do
    if git fetch -q origin main && git rebase -q origin/main; then
      if [ "$(git rev-list --count origin/main..HEAD)" = 0 ]; then
        return 0
      fi
      if git push -q origin HEAD:main; then
        echo "Gepusht."
        return 0
      fi
    else
      git rebase --abort 2>/dev/null
    fi
    sleep 10
  done
  echo "Pushen mislukt; volgende keer opnieuw." >&2
}

einde=$(( $(date +%s) + LOOPTIJD_MINUTEN * 60 ))
vorige=$(mktemp)
inhoud > "$vorige"
while :; do
  echo "=== $(date -u +'%H:%M UTC')"
  python3 tweakers_feed.py || echo "Ophalen mislukt; volgende keer opnieuw." >&2
  nu=$(mktemp)
  inhoud > "$nu"
  if cmp -s "$vorige" "$nu"; then
    rm "$nu"
    echo "Geen veranderingen in de artikelen."
  else
    mv "$nu" "$vorige"
    commit_en_push
  fi
  [ $(( $(date +%s) + INTERVAL_MINUTEN * 60 )) -lt "$einde" ] || break
  sleep $(( INTERVAL_MINUTEN * 60 ))
done
commit_en_push
rm -f "$vorige"
