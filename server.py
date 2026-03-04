#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Serveur de chat sécurisé avec chiffrement de bout en bout
Gère les messages privés, groupes, salon général et transfert de fichiers
"""

import socket
import threading
import json
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import logging
import os
import sys
from typing import Dict, Set, Optional, Any

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ChatServer')

class ChatServer:
    """Serveur de chat principal"""
    
    def __init__(self, host: str = '0.0.0.0', port: int = 5555):
        """
        Initialisation du serveur
        
        Args:
            host: Adresse d'écoute
            port: Port d'écoute
        """
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Dictionnaires pour stocker les clients connectés
        self.clients: Dict[int, Dict[str, Any]] = {}  # id_utilisateur -> {socket, nom, adresse}
        self.client_sockets: Dict[socket.socket, int] = {}  # socket -> id_utilisateur
        
        # Verrou pour la gestion des clients
        self.clients_lock = threading.Lock()
        
        # Connexion à la base de données
        self.db_connection = None
        self.connect_database()
        self.ensure_schema_extensions()
        
        # Création du salon général si nécessaire
        self.init_salon_general()
        
        logger.info(f"Serveur initialisé sur {host}:{port}")

    def ensure_schema_extensions(self):
        """Ajoute les extensions de schéma nécessaires (compatibilité rétroactive)."""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages_groupe_livraison (
                    message_groupe_id INT NOT NULL,
                    destinataire_id INT NOT NULL,
                    est_livre BOOLEAN DEFAULT FALSE,
                    date_livraison DATETIME NULL,
                    PRIMARY KEY (message_groupe_id, destinataire_id),
                    FOREIGN KEY (message_groupe_id) REFERENCES messages_groupe(id) ON DELETE CASCADE,
                    FOREIGN KEY (destinataire_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
                    INDEX idx_dest_non_livre (destinataire_id, est_livre)
                )
            """)
            cursor.close()
            self.db_connection.commit()
        except Error as e:
            logger.error(f"Erreur extension schéma: {e}")
    
    def connect_database(self):
        """Établit la connexion à la base de données MySQL"""
        try:
            self.db_connection = mysql.connector.connect(
                host='127.0.0.1',
                database='chat_app',
                user='ghislain',
                password='123456',
                autocommit=True
            )
            logger.info("Connexion à la base de données établie")
        except Error as e:
            logger.error(f"Erreur de connexion à la base de données: {e}")
            sys.exit(1)
    
    def init_salon_general(self):
        """Initialise le salon général et y ajoute tous les utilisateurs existants"""
        try:
            cursor = self.db_connection.cursor(dictionary=True)
            
            # Récupérer l'ID du salon général
            cursor.execute("SELECT id FROM groupes WHERE est_salon_general = TRUE")
            result = cursor.fetchone()
            
            if result:
                salon_id = result['id']
                
                # Ajouter tous les utilisateurs existants au salon général
                cursor.execute("""
                    INSERT IGNORE INTO membres_groupe (groupe_id, utilisateur_id)
                    SELECT %s, id FROM utilisateurs
                """, (salon_id,))
                
                logger.info("Salon général initialisé")
            cursor.close()
        except Error as e:
            logger.error(f"Erreur lors de l'initialisation du salon général: {e}")
    
    def start(self):
        """Démarre le serveur"""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            logger.info(f"Serveur en écoute sur {self.host}:{self.port}")
            
            while True:
                client_socket, client_address = self.server_socket.accept()
                logger.info(f"Nouvelle connexion de {client_address}")
                
                # Créer un thread pour gérer le nouveau client
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, client_address)
                )
                client_thread.daemon = True
                client_thread.start()
                
        except Exception as e:
            logger.error(f"Erreur serveur: {e}")
        finally:
            self.cleanup()
    
    def handle_client(self, client_socket: socket.socket, client_address: tuple):
        """
        Gère un client connecté
        
        Args:
            client_socket: Socket du client
            client_address: Adresse du client
        """
        user_id = None
        username = None
        
        try:
            # Authentification du client
            auth_data = self.receive_message(client_socket)
            if not auth_data or auth_data.get('type') != 'auth':
                return
            
            username = auth_data.get('username')
            if not username:
                return
            
            # Vérifier/créer l'utilisateur dans la base
            user_id = self.get_or_create_user(username)
            
            with self.clients_lock:
                # Vérifier si l'utilisateur est déjà connecté
                if user_id in self.clients:
                    self.send_error(client_socket, "Utilisateur déjà connecté")
                    return
                
                # Ajouter le client aux dictionnaires
                self.clients[user_id] = {
                    'socket': client_socket,
                    'nom': username,
                    'adresse': client_address,
                    'connexion': datetime.now()
                }
                self.client_sockets[client_socket] = user_id
            
            logger.info(f"Utilisateur {username} (ID: {user_id}) connecté")
            
            # Envoyer confirmation d'authentification
            self.send_message(client_socket, {
                'type': 'auth_success',
                'user_id': user_id,
                'username': username
            })
            
            # Mettre à jour la dernière connexion
            self.update_last_connection(user_id)
            
            # Envoyer les messages non livrés
            delivered_private_ids, delivered_group_ids = self.send_undelivered_messages(user_id, client_socket)
            
            # Envoyer l'historique des conversations
            self.send_conversation_history(
                user_id,
                client_socket,
                exclude_private_ids=delivered_private_ids,
                exclude_group_ids=delivered_group_ids
            )
            
            # Envoyer la liste des utilisateurs en ligne
            self.broadcast_user_list()
            
            # Ajouter l'utilisateur au salon général s'il n'y est pas déjà
            self.add_user_to_general_salon(user_id)
            
            # Boucle principale de réception des messages
            while True:
                data = self.receive_message(client_socket)
                if not data:
                    break
                
                self.process_client_message(user_id, username, data)
                
        except Exception as e:
            logger.error(f"Erreur avec le client {username}: {e}")
        finally:
            self.handle_disconnect(client_socket, user_id, username)
    
    def process_client_message(self, user_id: int, username: str, data: dict):
        """
        Traite un message reçu d'un client
        
        Args:
            user_id: ID de l'utilisateur
            username: Nom de l'utilisateur
            data: Données du message
        """
        msg_type = data.get('type')
        
        if msg_type == 'private_message':
            self.handle_private_message(user_id, username, data)
        elif msg_type == 'group_message':
            self.handle_group_message(user_id, username, data)
        elif msg_type == 'general_message':
            self.handle_general_message(user_id, username, data)
        elif msg_type == 'file_transfer':
            self.handle_file_transfer(user_id, username, data)
        elif msg_type == 'create_group':
            self.handle_create_group(user_id, data)
        elif msg_type == 'add_to_group':
            self.handle_add_to_group(user_id, data)
        else:
            logger.warning(f"Type de message inconnu: {msg_type}")
    
    def handle_private_message(self, sender_id: int, sender_name: str, data: dict):
        """
        Gère un message privé
        
        Args:
            sender_id: ID de l'expéditeur
            sender_name: Nom de l'expéditeur
            data: Données du message
        """
        recipient_name = data.get('recipient')
        encrypted_message = data.get('message')
        
        if not recipient_name or not encrypted_message:
            return
        
        # Récupérer l'ID du destinataire
        recipient_id = self.get_user_id(recipient_name)
        if not recipient_id:
            return
        
        # Stocker le message dans la base
        message_id = self.store_private_message(
            sender_id, recipient_id, encrypted_message, 
            is_file=False, filename=None
        )
        
        # Vérifier si le destinataire est en ligne
        with self.clients_lock:
            if recipient_id in self.clients:
                # Envoyer immédiatement
                self.send_message(self.clients[recipient_id]['socket'], {
                    'type': 'private_message',
                    'from': sender_name,
                    'message': encrypted_message,
                    'timestamp': datetime.now().isoformat(),
                    'message_id': message_id
                })
                
                # Marquer comme livré
                self.mark_message_delivered(message_id)
            else:
                logger.info(f"Message stocké pour {recipient_name} (hors-ligne)")
    
    def handle_group_message(self, sender_id: int, sender_name: str, data: dict):
        """
        Gère un message de groupe
        
        Args:
            sender_id: ID de l'expéditeur
            sender_name: Nom de l'expéditeur
            data: Données du message
        """
        group_name = data.get('group')
        encrypted_message = data.get('message')
        
        if not group_name or not encrypted_message:
            return
        
        # Récupérer l'ID du groupe
        group_id = self.get_group_id(group_name)
        if not group_id:
            return
        
        # Stocker le message
        message_id = self.store_group_message(
            group_id, sender_id, encrypted_message,
            is_file=False, filename=None
        )
        
        # Récupérer les membres du groupe
        members = self.get_group_members(group_id)
        recipients = [member_id for member_id in members if member_id != sender_id]
        self.create_group_delivery_entries(message_id, recipients)
        
        # Diffuser aux membres connectés
        with self.clients_lock:
            for member_id in recipients:
                if member_id in self.clients:
                    delivered = self.send_message(self.clients[member_id]['socket'], {
                        'type': 'group_message',
                        'group': group_name,
                        'from': sender_name,
                        'message': encrypted_message,
                        'timestamp': datetime.now().isoformat(),
                        'message_id': message_id
                    })
                    if delivered:
                        self.mark_group_message_delivered(message_id, member_id)
    
    def handle_general_message(self, sender_id: int, sender_name: str, data: dict):
        """
        Gère un message dans le salon général
        
        Args:
            sender_id: ID de l'expéditeur
            sender_name: Nom de l'expéditeur
            data: Données du message
        """
        encrypted_message = data.get('message')
        
        if not encrypted_message:
            return
        
        # Récupérer l'ID du salon général
        general_id = self.get_general_salon_id()
        if not general_id:
            return
        
        # Stocker le message
        message_id = self.store_group_message(
            general_id, sender_id, encrypted_message,
            is_file=False, filename=None
        )
        
        # Diffuser à tous les utilisateurs connectés
        with self.clients_lock:
            for user_id, client_info in self.clients.items():
                if user_id != sender_id:
                    self.send_message(client_info['socket'], {
                        'type': 'general_message',
                        'from': sender_name,
                        'message': encrypted_message,
                        'timestamp': datetime.now().isoformat(),
                        'message_id': message_id
                    })
    
    def handle_file_transfer(self, sender_id: int, sender_name: str, data: dict):
        """
        Gère le transfert d'un fichier
        
        Args:
            sender_id: ID de l'expéditeur
            sender_name: Nom de l'expéditeur
            data: Données du message
        """
        recipient = data.get('recipient')
        filename = data.get('filename')
        filesize = data.get('size')
        encrypted_data = data.get('data')
        
        if not all([recipient, filename, encrypted_data]):
            return
        
        recipient_id = self.get_user_id(recipient)
        if not recipient_id:
            return
        
        # Stocker le fichier dans la base
        message_id = self.store_private_message(
            sender_id, recipient_id, encrypted_data,
            is_file=True, filename=filename
        )
        
        # Vérifier si le destinataire est en ligne
        with self.clients_lock:
            if recipient_id in self.clients:
                # Envoyer immédiatement
                self.send_message(self.clients[recipient_id]['socket'], {
                    'type': 'file_transfer',
                    'from': sender_name,
                    'filename': filename,
                    'size': filesize,
                    'data': encrypted_data,
                    'timestamp': datetime.now().isoformat(),
                    'message_id': message_id
                })
                
                # Marquer comme livré
                self.mark_message_delivered(message_id)
            else:
                logger.info(f"Fichier {filename} stocké pour {recipient} (hors-ligne)")
    
    def handle_create_group(self, creator_id: int, data: dict):
        """
        Crée un nouveau groupe
        
        Args:
            creator_id: ID du créateur
            data: Données du message
        """
        group_name = data.get('group_name')
        
        if not group_name:
            return
        
        try:
            cursor = self.db_connection.cursor()
            
            # Créer le groupe
            cursor.execute(
                "INSERT INTO groupes (nom_groupe) VALUES (%s)",
                (group_name,)
            )
            group_id = cursor.lastrowid
            
            # Ajouter le créateur
            cursor.execute(
                "INSERT INTO membres_groupe (groupe_id, utilisateur_id) VALUES (%s, %s)",
                (group_id, creator_id)
            )
            
            cursor.close()
            self.db_connection.commit()
            
            logger.info(f"Groupe {group_name} créé par l'utilisateur {creator_id}")
            
        except Error as e:
            logger.error(f"Erreur lors de la création du groupe: {e}")
    
    def handle_add_to_group(self, adder_id: int, data: dict):
        """
        Ajoute un utilisateur à un groupe
        
        Args:
            adder_id: ID de la personne qui ajoute
            data: Données du message
        """
        group_name = data.get('group')
        username = data.get('username')
        
        if not group_name or not username:
            return
        
        group_id = self.get_group_id(group_name)
        user_id = self.get_user_id(username)
        
        if not group_id or not user_id:
            return
        
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(
                "INSERT IGNORE INTO membres_groupe (groupe_id, utilisateur_id) VALUES (%s, %s)",
                (group_id, user_id)
            )
            cursor.close()
            self.db_connection.commit()
            
            logger.info(f"Utilisateur {username} ajouté au groupe {group_name}")
            
        except Error as e:
            logger.error(f"Erreur lors de l'ajout au groupe: {e}")
    
    def handle_disconnect(self, client_socket: socket.socket, user_id: int, username: str):
        """
        Gère la déconnexion d'un client
        
        Args:
            client_socket: Socket du client
            user_id: ID de l'utilisateur
            username: Nom de l'utilisateur
        """
        with self.clients_lock:
            if client_socket in self.client_sockets:
                del self.client_sockets[client_socket]
            
            if user_id and user_id in self.clients:
                del self.clients[user_id]
        
        client_socket.close()
        
        if username:
            logger.info(f"Utilisateur {username} déconnecté")
            self.broadcast_user_list()
    
    def send_undelivered_messages(self, user_id: int, client_socket: socket.socket) -> tuple:
        """
        Envoie les messages non livrés à un utilisateur
        
        Args:
            user_id: ID de l'utilisateur
            client_socket: Socket du client
        Returns:
            Tuple (private_ids_livres, group_ids_livres).
        """
        delivered_private_ids = []
        delivered_group_ids = []
        try:
            cursor = self.db_connection.cursor(dictionary=True)
            
            # Récupérer les messages privés non livrés
            cursor.execute("""
                SELECT m.*, u.nom_utilisateur as expediteur_nom
                FROM messages_privés m
                JOIN utilisateurs u ON m.expediteur_id = u.id
                WHERE m.destinataire_id = %s AND m.est_livre = FALSE
                ORDER BY m.date_envoi ASC, m.id ASC
            """, (user_id,))
            
            undelivered = cursor.fetchall()
            
            for msg in undelivered:
                delivered = False
                if msg['est_fichier']:
                    delivered = self.send_message(client_socket, {
                        'type': 'file_transfer',
                        'from': msg['expediteur_nom'],
                        'filename': msg['nom_fichier'],
                        'data': msg['message_chiffre'],
                        'timestamp': msg['date_envoi'].isoformat(),
                        'message_id': msg['id']
                    })
                else:
                    delivered = self.send_message(client_socket, {
                        'type': 'private_message',
                        'from': msg['expediteur_nom'],
                        'message': msg['message_chiffre'],
                        'timestamp': msg['date_envoi'].isoformat(),
                        'message_id': msg['id']
                    })
                
                if delivered:
                    self.mark_message_delivered(msg['id'])
                    delivered_private_ids.append(msg['id'])
                else:
                    # Si l'envoi échoue (déconnexion brutale), on s'arrête
                    # pour conserver les messages restants non livrés.
                    break

            # Récupérer les messages de groupe non livrés pour cet utilisateur
            cursor.execute("""
                SELECT mg.id AS message_id, mg.message_chiffre, mg.date_envoi, mg.est_fichier,
                       mg.nom_fichier, g.nom_groupe, u.nom_utilisateur AS expediteur_nom
                FROM messages_groupe_livraison mgl
                JOIN messages_groupe mg ON mg.id = mgl.message_groupe_id
                JOIN groupes g ON g.id = mg.groupe_id
                JOIN utilisateurs u ON u.id = mg.expediteur_id
                WHERE mgl.destinataire_id = %s AND mgl.est_livre = FALSE
                ORDER BY mg.date_envoi ASC, mg.id ASC
            """, (user_id,))

            undelivered_groups = cursor.fetchall()
            for msg in undelivered_groups:
                delivered = False
                if msg['est_fichier']:
                    delivered = self.send_message(client_socket, {
                        'type': 'history_file',
                        'from': msg['expediteur_nom'],
                        'to': msg['nom_groupe'],
                        'filename': msg['nom_fichier'],
                        'data': msg['message_chiffre'],
                        'timestamp': msg['date_envoi'].isoformat(),
                        'message_id': msg['message_id'],
                        'is_outgoing': False,
                        'is_group': True
                    })
                else:
                    delivered = self.send_message(client_socket, {
                        'type': 'group_message',
                        'group': msg['nom_groupe'],
                        'from': msg['expediteur_nom'],
                        'message': msg['message_chiffre'],
                        'timestamp': msg['date_envoi'].isoformat(),
                        'message_id': msg['message_id']
                    })

                if delivered:
                    self.mark_group_message_delivered(msg['message_id'], user_id)
                    delivered_group_ids.append(msg['message_id'])
                else:
                    break
            
            cursor.close()
            
        except Error as e:
            logger.error(f"Erreur lors de l'envoi des messages non livrés: {e}")
        return delivered_private_ids, delivered_group_ids
    
    def send_conversation_history(
        self,
        user_id: int,
        client_socket: socket.socket,
        exclude_private_ids: Optional[list] = None,
        exclude_group_ids: Optional[list] = None
    ):
        """
        Envoie l'historique des conversations à un utilisateur
        
        Args:
            user_id: ID de l'utilisateur
            client_socket: Socket du client
        """
        try:
            cursor = self.db_connection.cursor(dictionary=True)
            exclude_private_ids = exclude_private_ids or []
            exclude_group_ids = exclude_group_ids or []
            exclude_clause = ""
            query_params = [user_id, user_id]
            if exclude_private_ids:
                placeholders = ", ".join(["%s"] * len(exclude_private_ids))
                exclude_clause = f" AND m.id NOT IN ({placeholders})"
                query_params.extend(exclude_private_ids)
            
            # Historique des messages privés (30 derniers jours)
            cursor.execute(f"""
                SELECT m.*, 
                       u1.nom_utilisateur as expediteur_nom,
                       u2.nom_utilisateur as destinataire_nom
                FROM messages_privés m
                JOIN utilisateurs u1 ON m.expediteur_id = u1.id
                JOIN utilisateurs u2 ON m.destinataire_id = u2.id
                WHERE (m.expediteur_id = %s OR m.destinataire_id = %s)
                AND m.date_envoi >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                {exclude_clause}
                ORDER BY m.date_envoi ASC, m.id ASC
            """, tuple(query_params))
            
            messages = cursor.fetchall()
            
            for msg in messages:
                if msg['est_fichier']:
                    self.send_message(client_socket, {
                        'type': 'history_file',
                        'from': msg['expediteur_nom'],
                        'to': msg['destinataire_nom'],
                        'filename': msg['nom_fichier'],
                        'data': msg['message_chiffre'],
                        'timestamp': msg['date_envoi'].isoformat(),
                        'message_id': msg['id'],
                        'is_outgoing': msg['expediteur_id'] == user_id
                    })
                else:
                    self.send_message(client_socket, {
                        'type': 'history_message',
                        'from': msg['expediteur_nom'],
                        'to': msg['destinataire_nom'],
                        'message': msg['message_chiffre'],
                        'timestamp': msg['date_envoi'].isoformat(),
                        'message_id': msg['id'],
                        'is_outgoing': msg['expediteur_id'] == user_id
                    })

            # Historique des groupes (30 derniers jours)
            group_exclude_clause = ""
            group_query_params = [user_id]
            if exclude_group_ids:
                placeholders = ", ".join(["%s"] * len(exclude_group_ids))
                group_exclude_clause = f" AND mg.id NOT IN ({placeholders})"
                group_query_params.extend(exclude_group_ids)

            cursor.execute(f"""
                SELECT mg.id, mg.message_chiffre, mg.date_envoi, mg.est_fichier, mg.nom_fichier,
                       g.nom_groupe, u.nom_utilisateur AS expediteur_nom, mg.expediteur_id
                FROM messages_groupe mg
                JOIN groupes g ON g.id = mg.groupe_id
                JOIN utilisateurs u ON u.id = mg.expediteur_id
                JOIN membres_groupe mem ON mem.groupe_id = g.id
                WHERE mem.utilisateur_id = %s
                AND mg.date_envoi >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                {group_exclude_clause}
                ORDER BY mg.date_envoi ASC, mg.id ASC
            """, tuple(group_query_params))
            group_messages = cursor.fetchall()

            for msg in group_messages:
                if msg['est_fichier']:
                    self.send_message(client_socket, {
                        'type': 'history_file',
                        'from': msg['expediteur_nom'],
                        'to': msg['nom_groupe'],
                        'filename': msg['nom_fichier'],
                        'data': msg['message_chiffre'],
                        'timestamp': msg['date_envoi'].isoformat(),
                        'message_id': msg['id'],
                        'is_outgoing': msg['expediteur_id'] == user_id,
                        'is_group': True
                    })
                else:
                    self.send_message(client_socket, {
                        'type': 'history_group_message',
                        'group': msg['nom_groupe'],
                        'from': msg['expediteur_nom'],
                        'message': msg['message_chiffre'],
                        'timestamp': msg['date_envoi'].isoformat(),
                        'message_id': msg['id'],
                        'is_outgoing': msg['expediteur_id'] == user_id
                    })
            
            cursor.close()
            
        except Error as e:
            logger.error(f"Erreur lors de l'envoi de l'historique: {e}")

    def create_group_delivery_entries(self, message_id: Optional[int], recipient_ids: list):
        """Crée les entrées de livraison groupe (une par destinataire)."""
        if not message_id or not recipient_ids:
            return
        try:
            cursor = self.db_connection.cursor()
            cursor.executemany(
                """
                INSERT IGNORE INTO messages_groupe_livraison
                (message_groupe_id, destinataire_id, est_livre)
                VALUES (%s, %s, FALSE)
                """,
                [(message_id, recipient_id) for recipient_id in recipient_ids]
            )
            cursor.close()
            self.db_connection.commit()
        except Error as e:
            logger.error(f"Erreur création livraisons groupe: {e}")

    def mark_group_message_delivered(self, message_id: int, recipient_id: int):
        """Marque un message de groupe comme livré pour un destinataire donné."""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(
                """
                UPDATE messages_groupe_livraison
                SET est_livre = TRUE, date_livraison = NOW()
                WHERE message_groupe_id = %s AND destinataire_id = %s
                """,
                (message_id, recipient_id)
            )
            cursor.close()
            self.db_connection.commit()
        except Error as e:
            logger.error(f"Erreur marquage livraison groupe: {e}")
    
    def broadcast_user_list(self):
        """Diffuse la liste des utilisateurs connectés à tous les clients"""
        with self.clients_lock:
            online_users = [
                {'id': user_id, 'nom': info['nom']}
                for user_id, info in self.clients.items()
            ]
        
        # Récupérer tous les utilisateurs de la base
        all_users = self.get_all_users()
        
        message = {
            'type': 'user_list',
            'online': online_users,
            'all_users': all_users
        }
        
        with self.clients_lock:
            for client_socket in self.client_sockets:
                self.send_message(client_socket, message)
    
    def get_or_create_user(self, username: str) -> Optional[int]:
        """
        Récupère ou crée un utilisateur
        
        Args:
            username: Nom d'utilisateur
            
        Returns:
            ID de l'utilisateur ou None
        """
        try:
            cursor = self.db_connection.cursor(dictionary=True)
            
            # Vérifier si l'utilisateur existe
            cursor.execute(
                "SELECT id FROM utilisateurs WHERE nom_utilisateur = %s",
                (username,)
            )
            result = cursor.fetchone()
            
            if result:
                user_id = result['id']
            else:
                # Créer le nouvel utilisateur
                cursor.execute(
                    "INSERT INTO utilisateurs (nom_utilisateur) VALUES (%s)",
                    (username,)
                )
                user_id = cursor.lastrowid
                
                # Ajouter au salon général
                self.add_user_to_general_salon(user_id)
            
            cursor.close()
            return user_id
            
        except Error as e:
            logger.error(f"Erreur lors de la récupération/création de l'utilisateur: {e}")
            return None
    
    def get_user_id(self, username: str) -> Optional[int]:
        """Récupère l'ID d'un utilisateur par son nom"""
        try:
            cursor = self.db_connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id FROM utilisateurs WHERE nom_utilisateur = %s",
                (username,)
            )
            result = cursor.fetchone()
            cursor.close()
            return result['id'] if result else None
        except Error as e:
            logger.error(f"Erreur lors de la récupération de l'ID: {e}")
            return None
    
    def get_all_users(self) -> list:
        """Récupère tous les utilisateurs"""
        try:
            cursor = self.db_connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, nom_utilisateur FROM utilisateurs ORDER BY nom_utilisateur"
            )
            users = cursor.fetchall()
            cursor.close()
            return [{'id': u['id'], 'nom': u['nom_utilisateur']} for u in users]
        except Error as e:
            logger.error(f"Erreur lors de la récupération des utilisateurs: {e}")
            return []
    
    def get_group_id(self, group_name: str) -> Optional[int]:
        """Récupère l'ID d'un groupe par son nom"""
        try:
            cursor = self.db_connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id FROM groupes WHERE nom_groupe = %s",
                (group_name,)
            )
            result = cursor.fetchone()
            cursor.close()
            return result['id'] if result else None
        except Error as e:
            logger.error(f"Erreur lors de la récupération de l'ID du groupe: {e}")
            return None
    
    def get_general_salon_id(self) -> Optional[int]:
        """Récupère l'ID du salon général"""
        try:
            cursor = self.db_connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id FROM groupes WHERE est_salon_general = TRUE"
            )
            result = cursor.fetchone()
            cursor.close()
            return result['id'] if result else None
        except Error as e:
            logger.error(f"Erreur lors de la récupération du salon général: {e}")
            return None
    
    def get_group_members(self, group_id: int) -> list:
        """Récupère les membres d'un groupe"""
        try:
            cursor = self.db_connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT utilisateur_id FROM membres_groupe WHERE groupe_id = %s",
                (group_id,)
            )
            members = cursor.fetchall()
            cursor.close()
            return [m['utilisateur_id'] for m in members]
        except Error as e:
            logger.error(f"Erreur lors de la récupération des membres du groupe: {e}")
            return []
    
    def add_user_to_general_salon(self, user_id: int):
        """Ajoute un utilisateur au salon général"""
        try:
            general_id = self.get_general_salon_id()
            if general_id:
                cursor = self.db_connection.cursor()
                cursor.execute(
                    "INSERT IGNORE INTO membres_groupe (groupe_id, utilisateur_id) VALUES (%s, %s)",
                    (general_id, user_id)
                )
                cursor.close()
                self.db_connection.commit()
        except Error as e:
            logger.error(f"Erreur lors de l'ajout au salon général: {e}")
    
    def store_private_message(self, sender_id: int, recipient_id: int, 
                             message: str, is_file: bool, filename: str = None) -> Optional[int]:
        """Stocke un message privé dans la base"""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute("""
                INSERT INTO messages_privés 
                (expediteur_id, destinataire_id, message_chiffre, est_fichier, nom_fichier)
                VALUES (%s, %s, %s, %s, %s)
            """, (sender_id, recipient_id, message, is_file, filename))
            
            message_id = cursor.lastrowid
            cursor.close()
            self.db_connection.commit()
            
            return message_id
        except Error as e:
            logger.error(f"Erreur lors du stockage du message: {e}")
            return None
    
    def store_group_message(self, group_id: int, sender_id: int,
                           message: str, is_file: bool, filename: str = None) -> Optional[int]:
        """Stocke un message de groupe dans la base"""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute("""
                INSERT INTO messages_groupe
                (groupe_id, expediteur_id, message_chiffre, est_fichier, nom_fichier)
                VALUES (%s, %s, %s, %s, %s)
            """, (group_id, sender_id, message, is_file, filename))
            
            message_id = cursor.lastrowid
            cursor.close()
            self.db_connection.commit()
            
            return message_id
        except Error as e:
            logger.error(f"Erreur lors du stockage du message de groupe: {e}")
            return None
    
    def mark_message_delivered(self, message_id: int):
        """Marque un message comme livré"""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(
                "UPDATE messages_privés SET est_livre = TRUE WHERE id = %s",
                (message_id,)
            )
            cursor.close()
            self.db_connection.commit()
        except Error as e:
            logger.error(f"Erreur lors du marquage du message: {e}")
    
    def update_last_connection(self, user_id: int):
        """Met à jour la date de dernière connexion"""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(
                "UPDATE utilisateurs SET derniere_connexion = NOW() WHERE id = %s",
                (user_id,)
            )
            cursor.close()
            self.db_connection.commit()
        except Error as e:
            logger.error(f"Erreur lors de la mise à jour de la connexion: {e}")
    
    def receive_message(self, client_socket: socket.socket) -> Optional[dict]:
        """
        Reçoit un message du client
        
        Args:
            client_socket: Socket du client
            
        Returns:
            Message décodé ou None
        """
        try:
            # Recevoir la taille du message
            raw_size = client_socket.recv(4)
            if not raw_size:
                return None
            
            msg_size = int.from_bytes(raw_size, byteorder='big')
            
            # Recevoir le message complet
            data = b''
            remaining = msg_size
            while remaining > 0:
                chunk = client_socket.recv(min(remaining, 4096))
                if not chunk:
                    return None
                data += chunk
                remaining -= len(chunk)
            
            return json.loads(data.decode('utf-8'))
            
        except Exception as e:
            logger.debug(f"Erreur lors de la réception: {e}")
            return None
    
    def send_message(self, client_socket: socket.socket, message: dict) -> bool:
        """
        Envoie un message au client
        
        Args:
            client_socket: Socket du client
            message: Message à envoyer
        """
        try:
            data = json.dumps(message).encode('utf-8')
            size = len(data).to_bytes(4, byteorder='big')
            client_socket.send(size + data)
            return True
        except Exception as e:
            logger.debug(f"Erreur lors de l'envoi: {e}")
            return False
    
    def send_error(self, client_socket: socket.socket, error_message: str):
        """Envoie un message d'erreur au client"""
        self.send_message(client_socket, {
            'type': 'error',
            'message': error_message
        })
    
    def cleanup(self):
        """Nettoie les ressources avant l'arrêt"""
        logger.info("Nettoyage des ressources...")
        
        # Fermer toutes les connexions clients
        with self.clients_lock:
            for client_socket in list(self.client_sockets.keys()):
                try:
                    client_socket.close()
                except:
                    pass
        
        # Fermer la connexion à la base
        if self.db_connection and self.db_connection.is_connected():
            self.db_connection.close()
        
        # Fermer le socket serveur
        self.server_socket.close()
        
        logger.info("Serveur arrêté")

if __name__ == "__main__":
    server = ChatServer()
    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("Arrêt demandé par l'utilisateur")
        server.cleanup()
