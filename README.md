# Import MySQL — interface graphique avec progression

Petite application Python (tkinter) pour importer un dump **`.sql`**, **`.sql.gz`** ou **`.tar.gz`** dans une base **MySQL** (testée pour MySQL 5.x), avec une barre de progression en pourcentage.

C'est l'équivalent graphique de la commande :

```bash
pv dump.sql | mysql -u root -p --reconnect MaBase
```

## Fonctionnalités

- Choix de la base de destination :
  - **base existante**, sélectionnée dans une liste récupérée depuis le serveur ;
  - **nouvelle base**, créée automatiquement avant l'import.
- Formats pris en charge : `.sql`, `.sql.gz`, `.tar.gz` / `.tgz` (le ou les fichiers `.sql` de l'archive sont lus directement, **sans décompression sur le disque**).
- Barre de progression avec pourcentage, taille traitée, vitesse, temps écoulé et temps restant estimé.
- Saisie du mot de passe masquée, transmis au client via `MYSQL_PWD` (il n'apparaît pas dans la liste des processus).
- Options : `--reconnect`, `--force`, jeu de caractères (`utf8`, `utf8mb4`, `latin1`).
- Bouton d'annulation et affichage des erreurs MySQL dans un journal.
- Aucune dépendance Python externe.

## Prérequis

- Python 3.6 ou supérieur avec tkinter
- Le client en ligne de commande `mysql` installé (dans le `PATH`, ou à indiquer dans la fenêtre)

Sous Debian / Ubuntu, si tkinter est absent :

```bash
sudo apt install python3-tk
```

## Utilisation

```bash
git clone https://github.com/<votre-compte>/<votre-depot>.git
cd <votre-depot>
python3 import_mysql.py
```

Sous Windows :

```bat
python import_mysql.py
```

Dans la fenêtre :

1. Renseignez l'hôte, le port, l'utilisateur et le mot de passe.
2. Choisissez le fichier à importer.
3. Cliquez sur **Charger les bases** puis sélectionnez la base cible, ou choisissez **Nouvelle base** et saisissez son nom.
4. Cliquez sur **Importer** et suivez la progression.

## Fonctionnement

Le programme lance le client `mysql` et lui envoie le contenu du dump par l'entrée standard, par blocs de 1 Mo, exactement comme le ferait `pv fichier.sql | mysql`. Le pourcentage est calculé à partir du nombre d'octets lus dans le fichier. Pour les fichiers compressés, il s'agit des octets compressés lus.

## Remarques

- Importer dans une **base existante** peut écraser des tables si le dump contient des instructions `DROP TABLE`. Une confirmation est demandée avant l'import.
- Le nom d'une nouvelle base est limité aux lettres, chiffres, `_`, `$` et `-`.
- Si l'archive `.tar.gz` ne contient aucun fichier `.sql`, l'import s'arrête avec un message d'erreur.
- Si une erreur survient pendant l'import, l'option `--force` permet de continuer malgré les erreurs SQL.

## Licence

Projet distribué sous licence MIT. Voir le fichier `LICENSE`.
