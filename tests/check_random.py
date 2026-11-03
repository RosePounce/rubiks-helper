"""Mélange aléatoire -> couleurs -> solution -> vérification."""
import random, sys, time
import numpy as np
from rubik_helper.puzzle import get_puzzle
from rubik_helper.solver import get_library, solve_colors

def run(pid, trials=3, nmoves=60, seed=1):
    pz = get_puzzle(pid)
    t = time.time(); lib = get_library(pz); tl = time.time() - t
    print(f"{pid}: bibliothèque {lib.stats} en {tl:.1f}s")
    rng = random.Random(seed)
    for i in range(trials):
        frame = [i for i in pz.frame_moves]
        seq = [rng.choice(frame) for _ in range(nmoves)]
        cont = pz.apply_seq(np.arange(pz.n), seq)
        # rotation globale aléatoire pour tester la détection du repère
        if i % 2 == 1:
            cont = pz.apply(cont, pz.symmetries[rng.randrange(len(pz.symmetries))])
        colors = pz.sticker_face[cont].tolist()
        for o in pz.orbits:
            if o.ignored:
                for p in o.pieces:
                    for s in pz.pieces[p]: colors[s] = -1
        t = time.time()
        res = solve_colors(pz, colors)
        dt = time.time() - t
        # vérification indépendante : appliquer la solution aux couleurs
        col = np.array(pz.sticker_face[cont])
        cur = cont
        for tok in pz.parse(" ".join(res["moves"])):
            perm = tok["perm"]
            cur = pz.apply(cur, perm)
        fc = res["face_colors"]
        ok = True
        for o in pz.orbits:
            if o.ignored or o.fixed: continue
            for p in o.pieces:
                for s in pz.pieces[p]:
                    if pz.sticker_face[cur[s]] != pz.sticker_face[cont[s]] * 0 + _home(pz, fc, s, cont):
                        ok = False
        print(f"   essai {i}: {res['move_count']} coups, {dt:.2f}s, ok={ok}")

def _home(pz, fc, s, cont):
    # couleur attendue sur s = fc[face(s)] ; couleur actuelle = face d'origine de cur[s]
    # fc est exprimé en couleurs = faces d'origine, donc on compare directement
    return fc[pz.sticker_face[s]]

if __name__ == "__main__":
    for pid in sys.argv[1:]:
        run(pid)
