-- Création de la base de données
CREATE DATABASE IF NOT EXISTS chat_app;
USE chat_app;

-- Table des utilisateurs
CREATE TABLE IF NOT EXISTS utilisateurs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nom_utilisateur VARCHAR(50) UNIQUE NOT NULL,
    date_inscription DATETIME DEFAULT CURRENT_TIMESTAMP,
    derniere_connexion DATETIME,
    INDEX idx_nom (nom_utilisateur)
);

-- Table des messages privés
CREATE TABLE IF NOT EXISTS messages_privés (
    id INT AUTO_INCREMENT PRIMARY KEY,
    expediteur_id INT NOT NULL,
    destinataire_id INT NOT NULL,
    message_chiffre TEXT NOT NULL,
    date_envoi DATETIME DEFAULT CURRENT_TIMESTAMP,
    est_livre BOOLEAN DEFAULT FALSE,
    est_fichier BOOLEAN DEFAULT FALSE,
    nom_fichier VARCHAR(255),
    FOREIGN KEY (expediteur_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
    FOREIGN KEY (destinataire_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
    INDEX idx_non_livre (destinataire_id, est_livre),
    INDEX idx_date (date_envoi)
);

-- Table des groupes
CREATE TABLE IF NOT EXISTS groupes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nom_groupe VARCHAR(100) UNIQUE NOT NULL,
    date_creation DATETIME DEFAULT CURRENT_TIMESTAMP,
    est_salon_general BOOLEAN DEFAULT FALSE
);

-- Table des membres des groupes
CREATE TABLE IF NOT EXISTS membres_groupe (
    groupe_id INT,
    utilisateur_id INT,
    date_ajout DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (groupe_id, utilisateur_id),
    FOREIGN KEY (groupe_id) REFERENCES groupes(id) ON DELETE CASCADE,
    FOREIGN KEY (utilisateur_id) REFERENCES utilisateurs(id) ON DELETE CASCADE
);

-- Table des messages de groupe
CREATE TABLE IF NOT EXISTS messages_groupe (
    id INT AUTO_INCREMENT PRIMARY KEY,
    groupe_id INT NOT NULL,
    expediteur_id INT NOT NULL,
    message_chiffre TEXT NOT NULL,
    date_envoi DATETIME DEFAULT CURRENT_TIMESTAMP,
    est_fichier BOOLEAN DEFAULT FALSE,
    nom_fichier VARCHAR(255),
    FOREIGN KEY (groupe_id) REFERENCES groupes(id) ON DELETE CASCADE,
    FOREIGN KEY (expediteur_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
    INDEX idx_groupe_date (groupe_id, date_envoi)
);

-- Table de livraison par destinataire pour les messages de groupe
CREATE TABLE IF NOT EXISTS messages_groupe_livraison (
    message_groupe_id INT NOT NULL,
    destinataire_id INT NOT NULL,
    est_livre BOOLEAN DEFAULT FALSE,
    date_livraison DATETIME NULL,
    PRIMARY KEY (message_groupe_id, destinataire_id),
    FOREIGN KEY (message_groupe_id) REFERENCES messages_groupe(id) ON DELETE CASCADE,
    FOREIGN KEY (destinataire_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
    INDEX idx_dest_non_livre (destinataire_id, est_livre)
);

-- Insertion du salon général par défaut
INSERT IGNORE INTO groupes (nom_groupe, est_salon_general) VALUES ('Général', TRUE);
