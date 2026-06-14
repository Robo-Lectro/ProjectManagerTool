# Party Manager - 25 ans mariage

Gestionnaire local et web pour organiser un party: invites, preparation, budget, message Messenger et projets sauvegardes.

## Ouvrir en local

Double-cliquer:

```text
Ouvrir_GUI_Invites.bat
```

Ou lancer:

```powershell
python gui_invites.py --port 8787
```

Puis ouvrir:

```text
http://127.0.0.1:8787
```

En local, les sauvegardes modifient directement les fichiers JSON.

## Ouvrir sur GitHub Pages

GitHub Pages peut servir la page comme site web statique. Dans ce mode, il n'y a pas de serveur Python, donc:

- le projet initial est lu depuis `json/projects/25ans-mariage.json`;
- les changements sont sauvegardes dans le navigateur;
- le bouton `Exporter JSON` permet de telecharger le projet modifie;
- le bouton `Importer JSON` permet de recharger un projet exporte.

Pour synchroniser entre appareils avec GitHub, exporter le JSON modifie, puis remplacer le fichier correspondant dans `json/projects/`.

## Fichiers importants

- `index.html`: entree GitHub Pages.
- `invites_gui.html`: interface Party Manager.
- `gui_invites.py`: serveur local pour sauvegarder directement.
- `json/projects/25ans-mariage.json`: projet principal.
- `MessagePublier`: message Messenger courant.
- `Recette.md`: choix et recette du party.
- `Tips_MarieClaude.md`: conseils et notes.

## GitHub Pages

Dans les parametres du repo GitHub:

1. Aller dans `Settings`.
2. Aller dans `Pages`.
3. Source: `GitHub Actions`.
4. Sauvegarder.
5. Retourner dans `Actions` et relancer `Deploy GitHub Pages` si le premier essai a echoue.

Le site ouvrira `index.html`, qui redirige vers le Party Manager.
