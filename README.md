# Rubik Helper

Solveur et guide pas à pas pour puzzles à rotation de faces :

| Puzzle | Équivalent | Pièces résolues |
|---|---|---|
| Cubes 3x3 à 7x7 | | coins, arêtes, ailes, tous les centres |
| Pyraminx | tétraèdre | coins, arêtes, pointes |
| Megaminx | 3x3 | coins, arêtes |
| Master Kilominx | 4x4 | coins, ailes, centres |
| Gigaminx | 5x5 | coins, arêtes, ailes, centres X et T |

## Lancer

```bash
uv run rubik-helper            # http://127.0.0.1:8000
uv run rubik-helper --port 8765
uv run rubik-helper --prepare  # précalcule toutes les bibliothèques puis quitte
uv run rubik-helper --lan      # réseau local en HTTPS, pour la caméra d'un téléphone
```

### Depuis un téléphone

Le navigateur n'autorise la caméra qu'en HTTPS hors de `localhost`. Avec `--lan`, le serveur
écoute sur toutes les interfaces, en HTTPS, avec un certificat auto-signé créé dans
`~/.cache/rubik-helper/tls/` (recréé si l'adresse IP de la machine change), et affiche les
adresses à ouvrir sur le téléphone, par exemple `https://192.168.1.20:8000`.

- Le téléphone doit être sur le même réseau que l'ordinateur.
- À la première visite, le navigateur signale un certificat non reconnu : choisir
  « Paramètres avancés », puis « Continuer vers le site ».
- Pare-feu : autoriser le port une fois par machine.
  - Ubuntu / Kubuntu (ufw) : `sudo ufw allow 8000/tcp`
  - Manjaro (firewalld, s'il est actif) : `sudo firewall-cmd --add-port=8000/tcp --permanent && sudo firewall-cmd --reload`
  - Windows : accepter la fenêtre du pare-feu au premier lancement (réseau privé).

Au premier lancement, les bibliothèques de commutateurs sont calculées en arrière-plan,
puis mises en cache dans `~/.cache/rubik-helper/` (variable `RUBIK_HELPER_CACHE` pour changer
d'emplacement). Comptez de quelques secondes pour un cube à environ 45 s pour le Gigaminx ou
le Master Kilominx, une seule fois.

## Version navigateur (GitHub Pages)

Le même outil tourne **entièrement dans le navigateur**, sans serveur : le moteur Python est
chargé par [Pyodide](https://pyodide.org) (CPython + numpy compilés en WebAssembly) et l'interface
appelle ce moteur au lieu d'une API HTTP. C'est ce qui permet de l'héberger sur GitHub Pages.

```bash
python web/build.py                 # assemble le site dans site/
python -m http.server -d site 8000  # puis ouvrir http://localhost:8000
```

Déploiement : le workflow `.github/workflows/pages.yml` construit `site/` et le publie à chaque
push sur `main` (activer Pages en mode « GitHub Actions » dans les réglages du dépôt).

À savoir : le premier chargement télécharge Pyodide et numpy (quelques Mo, une fois, mis en cache
par le navigateur) ; `kociemba` (solution courte du 3x3) n'est pas disponible dans le navigateur ;
et comme tout tourne sur le fil principal, la toute première résolution d'un gros cube fige
brièvement l'onglet le temps de bâtir sa bibliothèque (instantané pour le 3x3, le Pyraminx, le
4x4 et le Megaminx).

## Utilisation

1. Choisir le puzzle.
2. Saisir l'état mélangé, au choix :
   - **Peindre** : choisir une couleur, cliquer sur les facettes du patron ou de la vue 3D
     (Maj + clic remplit une face). Les compteurs signalent une couleur en trop.
   - **Caméra** : présenter chaque face selon le gabarit affiché (la face indiquée en haut),
     capturer, corriger si besoin, valider. Sur les puzzles à centre fixe (3x3, 5x5, Megaminx…),
     le centre de chaque face capturée sert d'étalon pour sa couleur, sous l'éclairage du moment ;
     commencer par la face blanche corrige aussi la dominante de la lumière pour les couleurs
     pas encore vues. La reconnaissance s'affine ensuite au fil des faces validées.
     Le navigateur n'autorise la caméra que sur `localhost` ou en https.
   - **Formule** : coller un mélange (notation WCA) ou générer un mélange aléatoire.
3. Cliquer sur **Résoudre**. Une saisie incohérente est signalée avec les facettes fautives
   entourées en rouge (pièce inexistante, pièce en double, coin tourné, parité impossible).
4. Suivre la solution avec le lecteur (flèches gauche/droite, espace). Chaque étape montre
   les coups à jouer, les pièces concernées en surbrillance et ce qu'elle dérange au passage.

## Aide-mémoire

L'onglet **Aide-mémoire** (à côté de Solution) donne, pour le puzzle choisi, les séquences à
connaître pour le résoudre sans l'outil : pour chaque étape (centres, arêtes, ailes, coins),
une ou deux séquences courtes qui échangent trois pièces, écrites en entier et découpées en
quatre temps (préparation, tour, préparation à l'envers, tour à l'envers), plus un exemple
avec coup de placement. Le bouton « Voir sur le puzzle » les joue dans la vue 3D, pièces
concernées en surbrillance. Les cas particuliers (parité, pièce tournée sur place) sont expliqués
à la fin.

Pour le 3x3, une **solution courte** (environ 20 coups, algorithme de Kociemba) est proposée
en plus du guide. Cette optimisation est **facultative** : elle repose sur `kociemba`, une
extension C qui exige un compilateur (Microsoft C++ Build Tools sous Windows). Sans elle,
l'application fonctionne normalement et omet simplement la solution courte. Pour l'activer :

```bash
uv sync --extra kociemba      # nécessite un compilateur C installé
```

## Puzzle mal remonté

Après une chute ou un démontage, un coin remis tourné ou deux pièces interverties rendent
le puzzle insoluble. Au lieu d'un simple refus, l'outil :

- désigne chaque pièce par ses couleurs et par les centres qui l'entourent
  (« coin jaune / blanc / bleu foncé, entre les centres blanc, vert foncé et rouge »),
  avec pour chaque face la couleur montrée et la couleur attendue ;
- fait clignoter la pièce en rouge et oriente la vue 3D sur elle (bouton « Montrer ») ;
- propose deux suites :
  - **Résoudre quand même** (recommandé) : la solution est jouée sur le puzzle tel qu'il est ;
    à la fin, tout est résolu sauf la ou les pièces à corriger à la main, montrées une à une ;
  - **J'ai corrigé le puzzle** : après avoir fait la correction indiquée, met à jour la saisie
    et relance la résolution.

Une pièce à sa place mais tournée est désignée avec certitude. Si le puzzle est mélangé,
la pièce fautive ne peut pas être identifiée mathématiquement : tourner n'importe quel coin
d'un tiers de tour rend l'état valable. C'est pourquoi « Résoudre quand même » est le plus
simple : le coin à tourner apparaît de lui-même à la fin.

## Algorithmes personnels

Le fichier `src/rubik_helper/algos.py` contient les algorithmes de l'utilisateur, que le solveur
emploie à la place de sa bibliothèque pour un type de pièce. Actuellement, pour les arêtes du 3x3 :
`F2 U M' U2 M U F2` (l'arête de devant part à gauche) et `F2 U' M' U2 M U' F2` (à droite), qui
échangent trois arêtes du haut. Les autres arêtes y sont amenées par des coups de placement
(faces extérieures, cinq au plus), défaits après l'algorithme. Les solutions du 3x3 sont un peu plus
longues (environ 110 coups), mais n'utilisent que cet algorithme pour les arêtes.

## Notation

- Cubes : `R U F L D B`, `'` et `2` ; `Rw` ou `r` = deux couches, `3Rw` = trois couches ;
  `2R` = deuxième tranche seule ; `M E S` = tranche centrale ; `x y z` = rotation du cube.
- Pyraminx : sommets `U L R B` ; `U` = 1/3 de tour horaire du coin et de ses arêtes, `U'` en sens
  inverse ; minuscules `u l r b` = la pointe seule.
- Famille Megaminx : faces `U F R BR BL L B DBL DL DR DBR D` ; `R` = 1/5 de tour horaire,
  `R2` = 2/5, `R2'` et `R'` en sens inverse ; `2R` = deuxième tranche (Gigaminx, Master Kilominx) ;
  `R++ R-- D++ D--` = mouvements des mélanges WCA (Pochmann).

## Méthode de résolution

Le moteur est générique : chaque puzzle est un polyèdre (cube, dodécaèdre ou tétraèdre) découpé
par des plans parallèles aux faces ; facettes, pièces, orbites et mouvements en sont déduits par
le calcul.

La résolution suit la méthode des commutateurs (celle de la résolution à l'aveugle « 3-style »),
dans l'ordre d'une réduction : centres, arêtes centrales, ailes, coins. Le Pyraminx fait exception :
ses coins et ses pointes ne changent jamais de place (on les oriente simplement sur place, les
coins avant les arêtes puis les pointes à la fin), seules les arêtes se résolvent par commutateurs.

1. **Parité** : si une orbite a une permutation impaire, un quart de tour la rend paire.
2. **3-cycles** : pour chaque orbite, chaque étape est un commutateur (placement, préparation, tour,
   préparation à l'envers, tour à l'envers, placement à l'envers) qui place deux pièces (parfois trois). À chaque étape, l'outil essaie tous les 3-cycles utiles
   et retient celui qui place le plus de pièces par coup joué ; pour les centres, interchangeables
   par couleur, le choix est très large. Il compare aussi avec la méthode classique à emplacement
   tampon et garde la plus courte.
   Un commutateur peut déranger des pièces d'une étape ultérieure, jamais celles déjà résolues.

Longueurs typiques : Pyraminx une quinzaine de coups, 3x3 environ 80 coups (et environ 20 avec la
solution courte), 4x4 environ 210, 5x5 environ 290, 6x6 environ 500, 7x7 environ 580, Megaminx
environ 200, Master Kilominx environ 535, Gigaminx environ 790. C'est long par rapport à une méthode de vitesse, mais chaque
étape est courte, indépendante et compréhensible.

## Limites connues

- **Master Kilominx** : modélisé comme un Gigaminx privé de ses pièces du milieu (centre, centres T,
  arêtes centrales), comme un 4x4 est un 5x5 sans sa tranche centrale. Le groupe de mouvements est
  le même, mais la vue 3D affiche ces zones en gris foncé, alors qu'elles n'existent pas sur le
  vrai puzzle.
- **Sens des mouvements `R++` / `D++`** : `R++` tourne tout sauf la couche DBL, `D++` tout sauf
  la couche U, de 2/5 de tour dans le sens horaire vu de R (ou de D). Cette convention reste à
  confirmer avec un mélange officiel avant de s'y fier.
- **Caméra** : la lecture des 12 couleurs d'un Megaminx (vert clair et vert foncé, crème et jaune)
  est fragile ; une vérification sur le patron reste nécessaire. Sans centre fixe (4x4, Pyraminx…),
  la première face lue sous une lumière chaude peut encore confondre bleu pâle et blanc : corriger
  puis valider, la couleur corrigée sert alors de référence.
- Les puzzles sans centre fixe (4x4, 6x6, Master Kilominx) déduisent le schéma de couleurs à partir
  des coins ; tous les coins doivent donc être saisis.

## Tests

```bash
uv run pytest -q            # tous les puzzles
uv run pytest -q -m "not slow"
```

## Structure

- `src/rubik_helper/geometry.py` : polyèdres, découpe des faces, rotations.
- `src/rubik_helper/puzzle.py` : pièces, orbites, mouvements, notation, catalogue.
- `src/rubik_helper/solver.py` : lecture de l'état, parité, bibliothèque de commutateurs, résolution.
- `src/rubik_helper/cheatsheet.py` : aide-mémoire (séquences à connaître par puzzle).
- `src/rubik_helper/extras.py` : palettes, patron 2D, mélanges, Kociemba.
- `src/rubik_helper/api.py` : cœur applicatif (fonctions pures, sans web), partagé serveur / navigateur.
- `src/rubik_helper/server.py` : couche HTTP FastAPI au-dessus de `api.py`.
- `src/rubik_helper/webglue.py` : pont navigateur (Pyodide), renvoie du JSON.
- `src/rubik_helper/static/` : interface (Three.js embarqué, fonctionne hors ligne).
- `web/` : `boot.js` (chargeur Pyodide) et `build.py` (assemble le site GitHub Pages).