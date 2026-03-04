#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Client de chat sécurisé avec interface graphique moderne
Version avec séparation stricte des conversations - CORRIGÉE
"""

import socket
import threading
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from cryptography.fernet import Fernet, InvalidToken
import base64
import os
import hashlib
from typing import Optional, Dict, List, Any, Tuple
from enum import Enum
import queue
from dataclasses import dataclass, field
from collections import defaultdict

class ConversationType(Enum):
    """Types de conversations possibles"""
    PRIVATE = "private"
    GROUP = "group"
    GENERAL = "general"

@dataclass
class Message:
    """Représente un message dans une conversation"""
    sender: str
    content: str
    timestamp: str
    is_outgoing: bool
    message_type: str  # 'text' ou 'file'
    filename: Optional[str] = None
    message_id: Optional[int] = None

@dataclass
class Conversation:
    """Représente une conversation"""
    id: str  # Identifiant unique (nom_utilisateur, nom_groupe ou "general")
    type: ConversationType
    name: str  # Nom affiché
    messages: List[Message] = field(default_factory=list)
    unread_count: int = 0

class ChatClient:
    """Client de chat avec interface graphique et séparation des conversations"""
    
    def __init__(self, host: str = 'localhost', port: int = 5555):
        """
        Initialisation du client
        
        Args:
            host: Adresse du serveur
            port: Port du serveur
        """
        self.host = host
        self.port = port
        self.socket = None
        self.connected = False
        self.username = None
        self.user_id = None
        
        # Configuration du chiffrement - Utiliser une clé fixe pour tous les clients
        self.setup_encryption()
        
        # File d'attente pour les messages de l'interface
        self.message_queue = queue.Queue()
        
        # Données de l'application
        self.users: Dict[int, str] = {}  # id -> nom
        self.online_users: List[int] = []  # liste des IDs en ligne
        self.groups: Dict[str, int] = {}  # nom_groupe -> id
        
        # Gestion des conversations
        self.conversations: Dict[str, Conversation] = {}  # id -> Conversation
        self.current_conversation_id: Optional[str] = None
        
        # Interface graphique
        self.root = tk.Tk()
        self.root.title("Chat Sécurisé")
        self.root.geometry("1100x700")
        
        # Configuration des styles
        self.setup_styles()
        
        # Interface de connexion
        self.setup_login_interface()
        
        # Traitement des messages en attente
        self.process_message_queue()
        
    def setup_encryption(self):
        """Configure le chiffrement avec une clé fixe pour tous les clients"""
        # Utiliser une clé fixe pour que tous les clients puissent déchiffrer les messages
        # IMPORTANT: Dans une vraie application, cette clé devrait être échangée de manière sécurisée
        self.encryption_key = Fernet.generate_key()  # Générer une clé
        print(f"Clé de chiffrement générée: {self.encryption_key.decode()}")
        
        # Pour que tous les clients utilisent la même clé, on utilise une clé fixe
        # Dans un environnement de production, vous voudriez partager cette clé de manière sécurisée
        fixed_key = base64.urlsafe_b64encode(b'01234567890123456789012345678901')  # 32 bytes
        self.cipher = Fernet(fixed_key)
        print("Chiffrement initialisé avec clé fixe")
        
    def setup_styles(self):
        """Configure les styles de l'interface"""
        style = ttk.Style()
        style.theme_use('clam')
        self.root.option_add("*Font", "{Segoe UI} 10")
        
        # Configuration des couleurs
        self.colors = {
            'bg': '#e9eef5',
            'panel_bg': '#f7f9fc',
            'sent_bg': '#d9fdd3',
            'received_bg': '#ffffff',
            'online': '#2e7d32',
            'offline': '#c62828',
            'unread': '#e53935',
            'selected': '#d7e8ff',
            'header': '#1f2937',
            'header_fg': '#ffffff',
            'conversation_hover': '#eef4ff',
            'text_muted': '#667085'
        }

        style.configure("TFrame", background=self.colors['panel_bg'])
        style.configure("TLabel", background=self.colors['panel_bg'], foreground="#111827")
        style.configure("TButton", padding=8, background="#2563eb", foreground="#ffffff", borderwidth=0)
        style.map("TButton", background=[("active", "#1d4ed8")])
        style.configure("TEntry", padding=6, fieldbackground="#ffffff")
        style.configure("TNotebook", background=self.colors['panel_bg'], tabmargins=(2, 2, 2, 0))
        style.configure("TNotebook.Tab", padding=(12, 8), font="{Segoe UI Semibold} 10")
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")])

        self.root.configure(bg=self.colors['bg'])
    
    def setup_login_interface(self):
        """Crée l'interface de connexion"""
        # Frame de connexion
        login_frame = ttk.Frame(self.root, padding="20")
        login_frame.pack(expand=True)
        
        ttk.Label(login_frame, text="Chat Sécurisé", 
                 font="{Segoe UI} 22 bold").pack(pady=20)
        
        ttk.Label(login_frame, text="Nom d'utilisateur:").pack(pady=5)
        self.username_entry = ttk.Entry(login_frame, width=30)
        self.username_entry.pack(pady=5)
        self.username_entry.bind('<Return>', lambda e: self.connect())
        
        ttk.Label(login_frame, text="Serveur:").pack(pady=5)
        self.server_entry = ttk.Entry(login_frame, width=30)
        self.server_entry.insert(0, f"{self.host}:{self.port}")
        self.server_entry.pack(pady=5)
        
        # Afficher la clé pour déboguer
        key_display = tk.StringVar()
        key_display.set("Clé fixe utilisée")
        ttk.Label(login_frame, textvariable=key_display, font="{Segoe UI} 8").pack(pady=5)
        
        ttk.Button(login_frame, text="Connexion", 
                  command=self.connect).pack(pady=20)
    
    def setup_main_interface(self):
        """Crée l'interface principale avec séparation des conversations"""
        # Nettoyer la fenêtre
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # Frame principal
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Panneau de gauche (liste des conversations)
        left_panel = ttk.Frame(main_frame, width=300)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=2, pady=2)
        left_panel.pack_propagate(False)
        
        # En-tête avec infos utilisateur
        self.setup_user_header(left_panel)
        
        # Notebook pour organiser les conversations
        notebook = ttk.Notebook(left_panel)
        notebook.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Onglet des conversations
        conversations_frame = ttk.Frame(notebook)
        notebook.add(conversations_frame, text="Conversations")
        
        # Liste des conversations avec scrollbar
        self.setup_conversations_list(conversations_frame)
        
        # Onglet des utilisateurs (pour démarrer de nouvelles conversations)
        users_frame = ttk.Frame(notebook)
        notebook.add(users_frame, text="Utilisateurs")
        self.setup_users_list(users_frame)
        
        # Onglet des groupes
        groups_frame = ttk.Frame(notebook)
        notebook.add(groups_frame, text="Groupes")
        self.setup_groups_list(groups_frame)
        
        # Panneau de droite (zone de chat)
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        # Zone de chat
        self.setup_chat_area(right_panel)
        
        # Initialiser la conversation générale
        self.init_general_conversation()
        
        # Mettre à jour les listes
        self.update_conversations_list()
        self.update_users_list()
    
    def setup_user_header(self, parent):
        """Configure l'en-tête avec les infos utilisateur"""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(header_frame, text=f"Connecté:",
                 font="{Segoe UI} 9").pack()
        ttk.Label(header_frame, text=self.username,
                 font="{Segoe UI} 11 bold").pack()
        
        # Séparateur
        ttk.Separator(parent, orient='horizontal').pack(fill=tk.X, pady=5)
    
    def setup_conversations_list(self, parent):
        """Configure la liste des conversations"""
        # Canvas pour le défilement
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        self.conversations_frame = ttk.Frame(canvas)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.create_window((0, 0), window=self.conversations_frame, anchor="nw", width=280)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        self.conversations_frame.bind("<Configure>", configure_scroll)
    
    def setup_users_list(self, parent):
        """Configure la liste des utilisateurs"""
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        self.users_list_frame = ttk.Frame(canvas)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.create_window((0, 0), window=self.users_list_frame, anchor="nw", width=280)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        self.users_list_frame.bind("<Configure>", configure_scroll)
    
    def setup_groups_list(self, parent):
        """Configure la liste des groupes"""
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        self.groups_list_frame = ttk.Frame(canvas)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.create_window((0, 0), window=self.groups_list_frame, anchor="nw", width=280)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        self.groups_list_frame.bind("<Configure>", configure_scroll)
        
        # Bouton pour créer un groupe
        ttk.Button(parent, text="Créer un groupe",
                  command=self.show_create_group_dialog).pack(pady=5)
    
    def setup_chat_area(self, parent):
        """Configure la zone de chat"""
        # En-tête de la conversation
        self.conversation_header = ttk.Frame(parent)
        self.conversation_header.pack(fill=tk.X, pady=5)
        
        self.conversation_title = ttk.Label(self.conversation_header,
                                           text="Sélectionnez une conversation",
                                           font="{Segoe UI} 12 bold")
        self.conversation_title.pack()
        
        # Séparateur
        ttk.Separator(parent, orient='horizontal').pack(fill=tk.X, pady=5)
        
        # Zone de messages avec scrollbar
        self.setup_messages_area(parent)
        
        # Zone de saisie
        self.setup_input_area(parent)
    
    def setup_messages_area(self, parent):
        """Configure la zone d'affichage des messages"""
        messages_container = ttk.Frame(parent)
        messages_container.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.messages_canvas = tk.Canvas(messages_container, highlightthickness=0,
                                        bg=self.colors['bg'])
        messages_scrollbar = ttk.Scrollbar(messages_container, orient="vertical",
                                          command=self.messages_canvas.yview)
        self.messages_frame = ttk.Frame(self.messages_canvas)
        
        self.messages_canvas.configure(yscrollcommand=messages_scrollbar.set)
        self.messages_canvas.create_window((0, 0), window=self.messages_frame,
                                          anchor="nw", width=780)
        
        self.messages_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        messages_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        def configure_scroll(event):
            self.messages_canvas.configure(scrollregion=self.messages_canvas.bbox("all"))
        
        self.messages_frame.bind("<Configure>", configure_scroll)
    
    def setup_input_area(self, parent):
        """Configure la zone de saisie"""
        input_frame = ttk.Frame(parent)
        input_frame.pack(fill=tk.X, pady=5)
        
        # Message
        message_frame = ttk.Frame(input_frame)
        message_frame.pack(fill=tk.X, pady=2)
        
        self.message_entry = ttk.Entry(message_frame)
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.message_entry.bind('<Return>', lambda e: self.send_text_message())
        self.message_entry.config(state='disabled')  # Désactivé par défaut
        
        ttk.Button(message_frame, text="Envoyer",
                  command=self.send_text_message).pack(side=tk.RIGHT, padx=2)
        
        ttk.Button(message_frame, text="📎 Fichier",
                  command=self.send_file).pack(side=tk.RIGHT, padx=2)
    
    def init_general_conversation(self):
        """Initialise la conversation du salon général"""
        general_conv = Conversation(
            id="general",
            type=ConversationType.GENERAL,
            name="Salon Général"
        )
        self.conversations["general"] = general_conv
    
    def get_or_create_conversation(self, conv_id: str, conv_type: ConversationType, name: str) -> Conversation:
        """
        Récupère ou crée une conversation
        
        Args:
            conv_id: Identifiant de la conversation
            conv_type: Type de conversation
            name: Nom affiché
            
        Returns:
            Conversation
        """
        if conv_id not in self.conversations:
            self.conversations[conv_id] = Conversation(
                id=conv_id,
                type=conv_type,
                name=name
            )
        return self.conversations[conv_id]
    
    def add_message_to_conversation(self, conv_id: str, message: Message):
        """
        Ajoute un message à une conversation
        
        Args:
            conv_id: Identifiant de la conversation
            message: Message à ajouter
        """
        if conv_id not in self.conversations:
            if conv_id == "general":
                self.get_or_create_conversation(conv_id, ConversationType.GENERAL, "Salon Général")
            elif conv_id.startswith("group_"):
                self.get_or_create_conversation(conv_id, ConversationType.GROUP, conv_id.replace("group_", ""))
            else:
                self.get_or_create_conversation(conv_id, ConversationType.PRIVATE, conv_id)

        # Éviter les doublons (vérifier par l'ID si disponible)
        if message.message_id is not None:
            for existing_msg in self.conversations[conv_id].messages:
                if existing_msg.message_id == message.message_id:
                    return  # Message déjà présent
        
        self.conversations[conv_id].messages.append(message)
        self.conversations[conv_id].messages.sort(
            key=lambda m: (m.timestamp or "", m.message_id or 0)
        )
        
        # Incrémenter le compteur de messages non lus si ce n'est pas la conversation courante
        if conv_id != self.current_conversation_id:
            self.conversations[conv_id].unread_count += 1
    
    def update_conversations_list(self):
        """Met à jour l'affichage de la liste des conversations"""
        if not hasattr(self, 'conversations_frame'):
            return
        
        # Nettoyer la liste
        for widget in self.conversations_frame.winfo_children():
            widget.destroy()
        
        # Trier les conversations (général en premier, puis privées, puis groupes)
        sorted_convs = sorted(
            self.conversations.values(),
            key=lambda c: (
                0 if c.type == ConversationType.GENERAL else
                1 if c.type == ConversationType.PRIVATE else 2,
                c.name.lower()
            )
        )
        
        for conv in sorted_convs:
            self.create_conversation_item(conv)
    
    def create_conversation_item(self, conv: Conversation):
        """
        Crée un élément de conversation dans la liste
        
        Args:
            conv: Conversation à afficher
        """
        frame = tk.Frame(self.conversations_frame, bg=self.colors['bg'], padx=5, pady=2)
        frame.pack(fill=tk.X, padx=2, pady=1)
        
        # Surligner si c'est la conversation courante
        if conv.id == self.current_conversation_id:
            frame.configure(bg=self.colors['selected'])
        
        # Indicateur de présence pour les conversations privées
        if conv.type == ConversationType.PRIVATE:
            user_id = self.get_user_id_by_name(conv.id)
            if user_id:
                presence_color = self.colors['online'] if user_id in self.online_users else self.colors['offline']
                presence_indicator = tk.Canvas(frame, width=10, height=10, highlightthickness=0, bg=frame['bg'])
                presence_indicator.create_oval(2, 2, 8, 8, fill=presence_color, outline=presence_color)
                presence_indicator.pack(side=tk.LEFT, padx=2)
        
        # Icône selon le type
        icon_text = "👤" if conv.type == ConversationType.PRIVATE else "👥" if conv.type == ConversationType.GROUP else "🏢"
        icon_label = tk.Label(frame, text=icon_text, bg=frame['bg'], font="{Segoe UI Emoji} 12")
        icon_label.pack(side=tk.LEFT, padx=2)
        
        # Nom de la conversation
        name_label = tk.Label(frame, text=conv.name, bg=frame['bg'], font="{Segoe UI} 10")
        name_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Compteur de messages non lus
        if conv.unread_count > 0:
            unread_label = tk.Label(frame, text=str(conv.unread_count), 
                                   bg=self.colors['unread'], fg='white',
                                   font="{Segoe UI} 8 bold", padx=4, pady=1)
            unread_label.pack(side=tk.RIGHT, padx=5)
        
        # Dernier message (aperçu)
        if conv.messages:
            last_msg = conv.messages[-1]
            preview_text = last_msg.content[:30] + "..." if len(last_msg.content) > 30 else last_msg.content
            preview_label = tk.Label(frame, text=preview_text, bg=frame['bg'],
                                    font="{Segoe UI} 8", fg=self.colors['text_muted'])
            preview_label.pack(side=tk.BOTTOM, anchor=tk.W, padx=20, pady=1)
        
        # Gestion des événements
        for widget in [frame, icon_label, name_label]:
            widget.bind('<Button-1>', lambda e, c=conv: self.select_conversation(c))
            widget.bind('<Enter>', lambda e, f=frame: f.configure(bg=self.colors['conversation_hover']))
            widget.bind('<Leave>', lambda e, f=frame, c=conv: f.configure(
                bg=self.colors['selected'] if c.id == self.current_conversation_id else self.colors['bg']
            ))
    
    def select_conversation(self, conv: Conversation):
        """
        Sélectionne une conversation
        
        Args:
            conv: Conversation à sélectionner
        """
        self.current_conversation_id = conv.id
        conv.unread_count = 0  # Remettre à zéro le compteur de messages non lus
        
        # Mettre à jour l'en-tête
        self.conversation_title.config(text=conv.name)
        
        # Activer la saisie
        self.message_entry.config(state='normal')
        self.message_entry.focus()
        
        # Afficher les messages
        self.display_conversation_messages(conv)
        
        # Mettre à jour la liste des conversations
        self.update_conversations_list()
    
    def display_conversation_messages(self, conv: Conversation):
        """
        Affiche les messages d'une conversation
        
        Args:
            conv: Conversation à afficher
        """
        # Nettoyer la zone de messages
        for widget in self.messages_frame.winfo_children():
            widget.destroy()
        
        # Afficher chaque message
        for msg in conv.messages:
            self.display_message_widget(msg)
        
        # Défiler vers le bas
        self.messages_frame.update_idletasks()
        self.messages_canvas.yview_moveto(1.0)
    
    def display_message_widget(self, message: Message):
        """
        Crée et affiche un widget message
        
        Args:
            message: Message à afficher
        """
        # Créer le conteneur du message
        msg_frame = ttk.Frame(self.messages_frame)
        
        # Alignement selon l'expéditeur
        if message.is_outgoing:
            msg_frame.pack(fill=tk.X, padx=10, pady=2, anchor=tk.E)
        else:
            msg_frame.pack(fill=tk.X, padx=10, pady=2, anchor=tk.W)
        
        # Cadre du message
        bubble_frame = tk.Frame(
            msg_frame,
            bg=self.colors['sent_bg'] if message.is_outgoing else self.colors['received_bg'],
            padx=10,
            pady=5
        )
        bubble_frame.pack()
        
        # En-tête (expéditeur et heure)
        header_frame = tk.Frame(bubble_frame, bg=bubble_frame['bg'])
        header_frame.pack(fill=tk.X)
        
        # Expéditeur
        sender_label = tk.Label(
            header_frame,
            text=message.sender,
            font="{Segoe UI} 9 bold",
            bg=bubble_frame['bg']
        )
        sender_label.pack(side=tk.LEFT)
        
        # Heure
        if message.timestamp:
            try:
                dt = datetime.fromisoformat(message.timestamp)
                time_str = dt.strftime("%H:%M")
            except:
                time_str = message.timestamp if len(message.timestamp) <= 5 else ""
            
            if time_str:
                time_label = tk.Label(
                    header_frame,
                    text=time_str,
                    font="{Segoe UI} 8",
                    bg=bubble_frame['bg'],
                    fg=self.colors['text_muted']
                )
                time_label.pack(side=tk.RIGHT, padx=(10, 0))
        
        # Contenu du message
        display_text = message.content
        if message.message_type == 'file':
            display_text = f"📎 {message.content}"
        
        message_label = tk.Label(
            bubble_frame,
            text=display_text,
            wraplength=500,
            justify=tk.LEFT,
            bg=bubble_frame['bg']
        )
        message_label.pack(anchor=tk.W)
    
    def update_users_list(self):
        """Met à jour l'affichage de la liste des utilisateurs"""
        if not hasattr(self, 'users_list_frame'):
            return
        
        # Nettoyer la liste
        for widget in self.users_list_frame.winfo_children():
            widget.destroy()
        
        # Afficher les utilisateurs
        for user_id, username in sorted(self.users.items(), key=lambda x: x[1]):
            if username == self.username:
                continue  # Ne pas s'afficher soi-même
            
            frame = ttk.Frame(self.users_list_frame)
            frame.pack(fill=tk.X, padx=2, pady=1)
            
            # Indicateur de présence
            canvas = tk.Canvas(frame, width=10, height=10, highlightthickness=0)
            color = self.colors['online'] if user_id in self.online_users else self.colors['offline']
            canvas.create_oval(2, 2, 8, 8, fill=color, outline=color)
            canvas.pack(side=tk.LEFT, padx=2)
            
            # Nom d'utilisateur
            label = ttk.Label(frame, text=username, cursor="hand2")
            label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            label.bind('<Button-1>', lambda e, u=username: self.start_private_conversation(u))
            
            frame.bind('<Button-1>', lambda e, u=username: self.start_private_conversation(u))
    
    def start_private_conversation(self, username: str):
        """
        Démarre une conversation privée avec un utilisateur
        
        Args:
            username: Nom de l'utilisateur
        """
        conv = self.get_or_create_conversation(
            conv_id=username,
            conv_type=ConversationType.PRIVATE,
            name=username
        )
        self.select_conversation(conv)
    
    def get_user_id_by_name(self, username: str) -> Optional[int]:
        """Récupère l'ID d'un utilisateur par son nom"""
        for user_id, name in self.users.items():
            if name == username:
                return user_id
        return None
    
    def connect(self):
        """Établit la connexion au serveur"""
        self.username = self.username_entry.get().strip()
        if not self.username:
            messagebox.showerror("Erreur", "Veuillez entrer un nom d'utilisateur")
            return
        
        # Extraire l'hôte et le port
        server_info = self.server_entry.get().strip()
        if ':' in server_info:
            self.host, port_str = server_info.split(':')
            self.port = int(port_str)
        
        try:
            # Connexion socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.connected = True
            
            # Envoyer les informations d'authentification
            self.send_to_server({
                'type': 'auth',
                'username': self.username
            })
            
            # Démarrer le thread de réception
            receive_thread = threading.Thread(target=self.receive_messages)
            receive_thread.daemon = True
            receive_thread.start()
            
        except Exception as e:
            messagebox.showerror("Erreur de connexion", str(e))
    
    def receive_messages(self):
        """Thread de réception des messages du serveur"""
        while self.connected:
            try:
                # Recevoir la taille du message
                raw_size = self.socket.recv(4)
                if not raw_size:
                    break
                
                msg_size = int.from_bytes(raw_size, byteorder='big')
                
                # Recevoir le message complet
                data = b''
                remaining = msg_size
                while remaining > 0:
                    chunk = self.socket.recv(min(remaining, 4096))
                    if not chunk:
                        break
                    data += chunk
                    remaining -= len(chunk)
                
                if data:
                    message = json.loads(data.decode('utf-8'))
                    self.message_queue.put(message)
                    
            except Exception as e:
                print(f"Erreur de réception: {e}")
                break
        
        self.connected = False
        self.root.after(0, self.handle_disconnection)
    
    def process_message_queue(self):
        """Traite les messages en attente dans l'interface"""
        try:
            while True:
                message = self.message_queue.get_nowait()
                self.handle_message(message)
        except queue.Empty:
            pass
        
        # Planifier le prochain traitement
        self.root.after(100, self.process_message_queue)
    
    def handle_message(self, message: dict):
        """
        Traite un message reçu
        
        Args:
            message: Message à traiter
        """
        msg_type = message.get('type')
        
        if msg_type == 'auth_success':
            self.handle_auth_success(message)
        elif msg_type == 'user_list':
            self.handle_user_list(message)
        elif msg_type == 'private_message':
            self.handle_private_message(message)
        elif msg_type == 'group_message':
            self.handle_group_message(message)
        elif msg_type == 'general_message':
            self.handle_general_message(message)
        elif msg_type == 'file_transfer':
            self.handle_file_transfer(message)
        elif msg_type == 'history_message':
            self.handle_history_message(message)
        elif msg_type == 'history_file':
            self.handle_history_file(message)
        elif msg_type == 'history_group_message':
            self.handle_history_group_message(message)
        elif msg_type == 'error':
            self.handle_error(message)
    
    def handle_auth_success(self, message: dict):
        """Gère la confirmation d'authentification"""
        self.user_id = message.get('user_id')
        self.root.after(0, self.setup_main_interface)
    
    def handle_user_list(self, message: dict):
        """Met à jour la liste des utilisateurs"""
        online_data = message.get('online', [])
        all_users_data = message.get('all_users', [])
        
        # Mettre à jour les dictionnaires
        self.users = {}
        for user in all_users_data:
            if isinstance(user, dict) and 'id' in user and 'nom' in user:
                self.users[user['id']] = user['nom']
        
        self.online_users = []
        for user in online_data:
            if isinstance(user, dict) and 'id' in user:
                self.online_users.append(user['id'])
        
        self.root.after(0, self.update_users_list)
        self.root.after(0, self.update_conversations_list)
    
    def handle_private_message(self, message: dict):
        """Gère un message privé reçu"""
        sender = message.get('from')
        encrypted_msg = message.get('message')
        timestamp = message.get('timestamp')
        message_id = message.get('message_id')
        
        if sender and encrypted_msg:
            try:
                decrypted_msg = self.decrypt_message(encrypted_msg)
                print(f"Message privé déchiffré de {sender}: {decrypted_msg[:30]}...")
                
                # Créer le message
                msg_obj = Message(
                    sender=sender,
                    content=decrypted_msg,
                    timestamp=timestamp,
                    is_outgoing=False,
                    message_type='text',
                    message_id=message_id
                )
                
                # Ajouter à la conversation
                self.root.after(0, lambda: self.add_message_to_conversation(sender, msg_obj))
                
                # Mettre à jour l'affichage si c'est la conversation courante
                if self.current_conversation_id == sender:
                    self.root.after(0, lambda: self.display_message_widget(msg_obj))
                    self.root.after(0, lambda: self.messages_canvas.yview_moveto(1.0))
                
                # Mettre à jour la liste des conversations
                self.root.after(0, self.update_conversations_list)
                
            except InvalidToken as e:
                print(f"Erreur de déchiffrement (token invalide): {e}")
                # Afficher un message d'erreur dans le chat
                error_msg = Message(
                    sender=sender,
                    content="[Message chiffré - clé incorrecte]",
                    timestamp=timestamp,
                    is_outgoing=False,
                    message_type='text'
                )
                self.root.after(0, lambda: self.add_message_to_conversation(sender, error_msg))
            except Exception as e:
                print(f"Erreur déchiffrement message privé: {e}")
    
    def handle_group_message(self, message: dict):
        """Gère un message de groupe reçu"""
        group = message.get('group')
        sender = message.get('from')
        encrypted_msg = message.get('message')
        timestamp = message.get('timestamp')
        message_id = message.get('message_id')
        
        if all([group, sender, encrypted_msg]):
            try:
                decrypted_msg = self.decrypt_message(encrypted_msg)
                print(f"Message de groupe déchiffré de {sender} dans {group}")
                
                # Créer le message
                msg_obj = Message(
                    sender=sender,
                    content=decrypted_msg,
                    timestamp=timestamp,
                    is_outgoing=False,
                    message_type='text',
                    message_id=message_id
                )
                
                # Ajouter à la conversation
                conv_id = f"group_{group}"
                self.root.after(0, lambda: self.add_message_to_conversation(conv_id, msg_obj))
                
                # Mettre à jour l'affichage si c'est la conversation courante
                if self.current_conversation_id == conv_id:
                    self.root.after(0, lambda: self.display_message_widget(msg_obj))
                    self.root.after(0, lambda: self.messages_canvas.yview_moveto(1.0))
                
                # Mettre à jour la liste des conversations
                self.root.after(0, self.update_conversations_list)
                
            except InvalidToken as e:
                print(f"Erreur de déchiffrement groupe: {e}")
            except Exception as e:
                print(f"Erreur déchiffrement message groupe: {e}")
    
    def handle_general_message(self, message: dict):
        """Gère un message du salon général"""
        sender = message.get('from')
        encrypted_msg = message.get('message')
        timestamp = message.get('timestamp')
        message_id = message.get('message_id')
        
        if sender and encrypted_msg:
            try:
                decrypted_msg = self.decrypt_message(encrypted_msg)
                print(f"Message général déchiffré de {sender}")
                
                # Créer le message
                msg_obj = Message(
                    sender=sender,
                    content=decrypted_msg,
                    timestamp=timestamp,
                    is_outgoing=False,
                    message_type='text',
                    message_id=message_id
                )
                
                # Ajouter à la conversation générale
                self.root.after(0, lambda: self.add_message_to_conversation("general", msg_obj))
                
                # Mettre à jour l'affichage si c'est la conversation courante
                if self.current_conversation_id == "general":
                    self.root.after(0, lambda: self.display_message_widget(msg_obj))
                    self.root.after(0, lambda: self.messages_canvas.yview_moveto(1.0))
                
                # Mettre à jour la liste des conversations
                self.root.after(0, self.update_conversations_list)
                
            except InvalidToken as e:
                print(f"Erreur de déchiffrement général: {e}")
            except Exception as e:
                print(f"Erreur déchiffrement message général: {e}")
    
    def handle_file_transfer(self, message: dict):
        """Gère la réception d'un fichier"""
        sender = message.get('from')
        filename = message.get('filename')
        encrypted_data = message.get('data')
        timestamp = message.get('timestamp')
        message_id = message.get('message_id')
        
        if all([sender, filename, encrypted_data]):
            # Proposer de sauvegarder le fichier
            save_path = filedialog.asksaveasfilename(
                initialfile=filename,
                title=f"Enregistrer le fichier de {sender}"
            )
            
            if save_path:
                try:
                    # Déchiffrer et sauvegarder
                    decrypted_data = self.cipher.decrypt(
                        base64.b64decode(encrypted_data.encode())
                    )
                    
                    with open(save_path, 'wb') as f:
                        f.write(decrypted_data)
                    
                    messagebox.showinfo("Succès", f"Fichier {filename} enregistré")
                    
                except Exception as e:
                    messagebox.showerror("Erreur", f"Erreur lors de la sauvegarde: {e}")
            
            # Créer un message de notification
            msg_obj = Message(
                sender=sender,
                content=f"Fichier reçu: {filename}",
                timestamp=timestamp,
                is_outgoing=False,
                message_type='file',
                filename=filename,
                message_id=message_id
            )
            
            # Ajouter à la conversation
            self.root.after(0, lambda: self.add_message_to_conversation(sender, msg_obj))
            
            # Mettre à jour l'affichage si c'est la conversation courante
            if self.current_conversation_id == sender:
                self.root.after(0, lambda: self.display_message_widget(msg_obj))
                self.root.after(0, lambda: self.messages_canvas.yview_moveto(1.0))
            
            # Mettre à jour la liste des conversations
            self.root.after(0, self.update_conversations_list)
    
    def handle_history_message(self, message: dict):
        """Gère un message de l'historique"""
        sender = message.get('from')
        recipient = message.get('to')
        encrypted_msg = message.get('message')
        timestamp = message.get('timestamp')
        message_id = message.get('message_id')
        is_outgoing = message.get('is_outgoing', False)
        
        if encrypted_msg:
            try:
                decrypted_msg = self.decrypt_message(encrypted_msg)
                print(f"Message historique déchiffré - de: {sender}, vers: {recipient}")
                
                # Déterminer la conversation
                if is_outgoing:
                    conv_id = recipient
                else:
                    conv_id = sender
                
                # Créer le message
                msg_obj = Message(
                    sender=sender if not is_outgoing else "Vous",
                    content=decrypted_msg,
                    timestamp=timestamp,
                    is_outgoing=is_outgoing,
                    message_type='text',
                    message_id=message_id
                )
                
                # Ajouter à la conversation
                self.root.after(0, lambda: self.add_message_to_conversation(conv_id, msg_obj))
                
            except InvalidToken as e:
                print(f"Erreur de déchiffrement historique (token invalide): {e}")
            except Exception as e:
                print(f"Erreur déchiffrement historique: {e}")
    
    def handle_history_file(self, message: dict):
        """Gère un fichier de l'historique"""
        sender = message.get('from')
        recipient = message.get('to')
        filename = message.get('filename')
        timestamp = message.get('timestamp')
        message_id = message.get('message_id')
        is_outgoing = message.get('is_outgoing', False)
        is_group = message.get('is_group', False)
        
        # Déterminer la conversation
        if is_group:
            conv_id = f"group_{recipient}"
        elif is_outgoing:
            conv_id = recipient
        else:
            conv_id = sender
        
        # Créer le message
        msg_obj = Message(
            sender=sender if not is_outgoing else "Vous",
            content=f"Fichier: {filename}",
            timestamp=timestamp,
            is_outgoing=is_outgoing,
            message_type='file',
            filename=filename,
            message_id=message_id
        )
        
        # Ajouter à la conversation
        self.root.after(0, lambda: self.add_message_to_conversation(conv_id, msg_obj))

    def handle_history_group_message(self, message: dict):
        """Gère un message texte de groupe provenant de l'historique."""
        group = message.get('group')
        sender = message.get('from')
        encrypted_msg = message.get('message')
        timestamp = message.get('timestamp')
        message_id = message.get('message_id')
        is_outgoing = message.get('is_outgoing', False)

        if all([group, sender, encrypted_msg]):
            try:
                decrypted_msg = self.decrypt_message(encrypted_msg)
                conv_id = f"group_{group}"
                msg_obj = Message(
                    sender="Vous" if is_outgoing else sender,
                    content=decrypted_msg,
                    timestamp=timestamp,
                    is_outgoing=is_outgoing,
                    message_type='text',
                    message_id=message_id
                )
                self.root.after(0, lambda: self.add_message_to_conversation(conv_id, msg_obj))
            except Exception as e:
                print(f"Erreur historique groupe: {e}")
    
    def handle_error(self, message: dict):
        """Affiche une erreur"""
        error_msg = message.get('message', 'Erreur inconnue')
        self.root.after(0, lambda: messagebox.showerror("Erreur", error_msg))
    
    def handle_disconnection(self):
        """Gère la déconnexion du serveur"""
        if hasattr(self, 'setup_login_interface'):
            self.setup_login_interface()
        messagebox.showwarning("Déconnexion", "Déconnecté du serveur")
    
    def show_create_group_dialog(self):
        """Affiche la boîte de dialogue de création de groupe"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Créer un groupe")
        dialog.geometry("400x400")
        
        ttk.Label(dialog, text="Nom du groupe:").pack(pady=5)
        group_name_entry = ttk.Entry(dialog, width=30)
        group_name_entry.pack(pady=5)
        
        ttk.Label(dialog, text="Sélectionner les membres:").pack(pady=5)
        
        # Liste des utilisateurs avec cases à cocher
        members_frame = ttk.Frame(dialog)
        members_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        canvas = tk.Canvas(members_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(members_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        members_vars = {}
        for user_id, username in self.users.items():
            if username != self.username:
                var = tk.BooleanVar()
                cb = ttk.Checkbutton(scrollable_frame, text=username, variable=var)
                cb.pack(anchor=tk.W, pady=2)
                members_vars[username] = var
        
        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        scrollable_frame.bind("<Configure>", configure_scroll)
        
        def create_group():
            group_name = group_name_entry.get().strip()
            if not group_name:
                messagebox.showerror("Erreur", "Veuillez entrer un nom de groupe")
                return
            
            selected_members = [
                username for username, var in members_vars.items()
                if var.get()
            ]
            
            if not selected_members:
                messagebox.showerror("Erreur", "Sélectionnez au moins un membre")
                return
            
            # Créer le groupe
            self.send_to_server({
                'type': 'create_group',
                'group_name': group_name
            })
            
            # Ajouter les membres
            for member in selected_members:
                self.send_to_server({
                    'type': 'add_to_group',
                    'group': group_name,
                    'username': member
                })
            
            # Ajouter le créateur aussi
            self.send_to_server({
                'type': 'add_to_group',
                'group': group_name,
                'username': self.username
            })
            
            # Créer la conversation de groupe
            conv_id = f"group_{group_name}"
            conv = Conversation(
                id=conv_id,
                type=ConversationType.GROUP,
                name=group_name
            )
            self.conversations[conv_id] = conv
            
            dialog.destroy()
            self.update_conversations_list()
            messagebox.showinfo("Succès", f"Groupe {group_name} créé")
        
        ttk.Button(dialog, text="Créer", command=create_group).pack(pady=10)
    
    def send_text_message(self):
        """Envoie un message texte"""
        if not self.current_conversation_id:
            messagebox.showwarning("Attention", "Sélectionnez d'abord une conversation")
            return
        
        message = self.message_entry.get().strip()
        if not message:
            return
        
        conv = self.conversations[self.current_conversation_id]
        
        # Chiffrer le message
        try:
            encrypted = self.encrypt_message(message)
            print(f"Message chiffré: {encrypted[:30]}...")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de chiffrer le message: {e}")
            return
        
        # Envoyer selon le type de conversation
        if conv.type == ConversationType.PRIVATE:
            self.send_to_server({
                'type': 'private_message',
                'recipient': conv.id,
                'message': encrypted
            })
        elif conv.type == ConversationType.GROUP:
            # Extraire le nom du groupe (sans le préfixe "group_")
            group_name = conv.id.replace("group_", "")
            self.send_to_server({
                'type': 'group_message',
                'group': group_name,
                'message': encrypted
            })
        elif conv.type == ConversationType.GENERAL:
            self.send_to_server({
                'type': 'general_message',
                'message': encrypted
            })
        
        # Créer le message local
        msg_obj = Message(
            sender="Vous",
            content=message,
            timestamp=datetime.now().isoformat(),
            is_outgoing=True,
            message_type='text'
        )
        
        # Ajouter à la conversation
        self.add_message_to_conversation(conv.id, msg_obj)
        
        # Afficher le message
        self.display_message_widget(msg_obj)
        
        # Nettoyer et défiler
        self.message_entry.delete(0, tk.END)
        self.messages_canvas.yview_moveto(1.0)
        
        # Mettre à jour la liste des conversations
        self.update_conversations_list()
    
    def send_file(self):
        """Envoie un fichier"""
        if not self.current_conversation_id:
            messagebox.showwarning("Attention", "Sélectionnez d'abord une conversation")
            return
        
        conv = self.conversations[self.current_conversation_id]
        
        if conv.type != ConversationType.PRIVATE:
            messagebox.showwarning("Attention", 
                                  "L'envoi de fichiers n'est disponible qu'en privé pour l'instant")
            return
        
        filename = filedialog.askopenfilename()
        if not filename:
            return
        
        try:
            # Lire et chiffrer le fichier
            with open(filename, 'rb') as f:
                file_data = f.read()
            
            encrypted_data = self.cipher.encrypt(file_data)
            encrypted_b64 = base64.b64encode(encrypted_data).decode()
            
            # Envoyer au serveur
            self.send_to_server({
                'type': 'file_transfer',
                'recipient': conv.id,
                'filename': os.path.basename(filename),
                'size': len(file_data),
                'data': encrypted_b64
            })
            
            # Créer le message de notification
            msg_obj = Message(
                sender="Vous",
                content=f"Envoi du fichier: {os.path.basename(filename)}",
                timestamp=datetime.now().isoformat(),
                is_outgoing=True,
                message_type='file',
                filename=os.path.basename(filename)
            )
            
            # Ajouter à la conversation
            self.add_message_to_conversation(conv.id, msg_obj)
            
            # Afficher le message
            self.display_message_widget(msg_obj)
            self.messages_canvas.yview_moveto(1.0)
            
            # Mettre à jour la liste des conversations
            self.update_conversations_list()
            
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur lors de l'envoi du fichier: {e}")
    
    def encrypt_message(self, message: str) -> str:
        """Chiffre un message"""
        encrypted = self.cipher.encrypt(message.encode())
        return base64.b64encode(encrypted).decode()
    
    def decrypt_message(self, encrypted_message: str) -> str:
        """Déchiffre un message"""
        decrypted = self.cipher.decrypt(
            base64.b64decode(encrypted_message.encode())
        )
        return decrypted.decode()
    
    def send_to_server(self, message: dict):
        """Envoie un message au serveur"""
        try:
            data = json.dumps(message).encode('utf-8')
            size = len(data).to_bytes(4, byteorder='big')
            self.socket.send(size + data)
        except Exception as e:
            print(f"Erreur d'envoi: {e}")
            self.connected = False
    
    def run(self):
        """Lance l'application"""
        self.root.mainloop()
        
        # Nettoyage
        self.connected = False
        if self.socket:
            self.socket.close()

if __name__ == "__main__":
    client = ChatClient()
    client.run()
