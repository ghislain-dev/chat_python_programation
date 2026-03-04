# contributeur
- # GHISLAIN MUNDEKE KASEREKA
- # KASEREKA KIPOSO MARC
# Chat App Python (Client/Serveur chiffré)

Application de messagerie temps réel en Python avec:
- communication TCP sockets
- interface graphique Tkinter
- persistance MySQL
- gestion des conversations privées, groupes et salon général
- livraison des messages hors-ligne à la reconnexion
- historique des conversations

## Fonctionnalités

- Authentification simple par nom d'utilisateur
- Messages privés chiffrés (le serveur stocke/transmet sans déchiffrer)
- Messages de groupe
- Salon général
- Envoi de fichiers en privé
- Historique des messages
- Messages hors-ligne:
  - stockage en base quand le destinataire est absent
  - livraison automatique à la reconnexion
  - marquage livré après envoi réussi
- Indicateur de présence en ligne/hors ligne
- Interface de chat moderne (Tkinter + ttk)

## Architecture

- `server.py`
  - serveur TCP multiclient (thread par client)
  - gestion des utilisateurs connectés
  - persistance MySQL
  - diffusion des messages privés/groupes/général
  - livraison hors-ligne + historique

- `client.py`
  - client GUI Tkinter
  - réception asynchrone via thread socket + queue UI
  - séparation stricte des conversations
  - déduplication des messages par `message_id`

- `database/schema.sql`
  - schéma de base de données (`chat_app`)
  - tables utilisateurs/messages/groupes/membres/livraisons

## Pré-requis

- Python 3.10+ (testé sur Python 3.13)
- MySQL / MariaDB
- pip

## Installation

1. Cloner le projet et entrer dans le dossier:

```bash
cd /home/aspirantdev/Bureau/chat_app
```

2. Créer un environnement virtuel et l'activer:

```bash
python3 -m venv chat_env
source chat_env/bin/activate
```

3. Installer les dépendances:

```bash
pip install cryptography mysql-connector-python
```

4. Initialiser la base:

```bash
mysql -u <user_mysql> -p < database/schema.sql
```

## Configuration

Dans `server.py`, adapter la méthode `connect_database()`:
- `host`
- `database`
- `user`
- `password`

Exemple actuel dans le code:
- host: `127.0.0.1`
- database: `chat_app`
- user: `ghislain`
- password: `123456`

## Lancer l'application

1. Démarrer le serveur:

```bash
python3 server.py
```

2. Démarrer un ou plusieurs clients (dans d'autres terminaux):

```bash
python3 client.py
```

3. Dans l'écran de connexion client:
- saisir un nom d'utilisateur
- laisser `localhost:5555` ou mettre l'adresse du serveur

## Flux messages hors-ligne

1. Utilisateur A envoie un message à B.
2. Si B est hors-ligne:
   - le message chiffré est enregistré en MySQL (`non livré`)
3. Au login de B:
   - le serveur envoie tous ses messages non livrés (ordre chrono)
   - marque chaque message livré uniquement si l'envoi réussit
4. Ensuite le serveur envoie l'historique (sans doublonner les messages déjà livrés dans cette session).

Le même principe est appliqué aux messages de groupe via une table de livraison par destinataire.

## Schéma de données (résumé)

- `utilisateurs`
- `messages_privés`
- `groupes`
- `membres_groupe`
- `messages_groupe`
- `messages_groupe_livraison`

## Limites actuelles

- Clé de chiffrement partagée et fixe côté client (démonstration, non production)
- Pas d'authentification forte (nom d'utilisateur seul)
- Pas de TLS transport
- Upload de fichier limité au privé

## Pistes d'amélioration

- Authentification (mot de passe + hash + session)
- Rotation de clés / échange sécurisé des clés
- TLS (`ssl`) sur sockets
- Accusés de réception côté client
- Pagination de l'historique
- Tests d'intégration automatisés (offline/reconnect/groupes)

## Dépannage rapide

- Erreur MySQL:
  - vérifier service MySQL actif
  - vérifier identifiants dans `server.py`
  - vérifier que la base `chat_app` existe

- Port occupé (`5555`):
  - changer le port dans `server.py` et dans le client

- Le client ne se connecte pas:
  - vérifier `host:port` dans le champ "Serveur"
  - vérifier que le serveur tourne
